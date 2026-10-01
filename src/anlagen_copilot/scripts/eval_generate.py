"""Measure the generated answers against the eval set.

The counterpart to `eval_retrieval.py` for the last stage: every question runs
through retrieval, reranking and generation, and the answer is scored by which
pages it cites. No model grades the answers here; the scores follow from the
pages alone and come out the same for the same answer.
"""

import argparse
import collections
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt, model_validator

from anlagen_copilot.clients import get_anthropic_client, get_openai_client
from anlagen_copilot.db import get_connection
from anlagen_copilot.eval import EvalQuestion, ExpectedSource, load_eval
from anlagen_copilot.generate import GeneratedAnswer, Statement, generate
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.paths import DATA_DIR
from anlagen_copilot.pipeline import select_pages
from anlagen_copilot.retrieval import Source
from anlagen_copilot.runlog import append_run, current_commit, median_seconds
from anlagen_copilot.settings import Strategy, get_settings

logger = logging.getLogger(__name__)

DEFAULT_GENERATION_RUNS_PATH = DATA_DIR / "generation/eval_runs.jsonl"


class PageRef(BaseModel):
    """One manual page, identified by document and page number.

    Frozen, so it can go into a set: the scoring compares pages as sets, and a
    page cited in several statements must count once.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page: PositiveInt


class Score(BaseModel):
    """How the required pages of one question fared, from the eval set to the answer.

    `required` pages come from the eval set, `retrieved` of them reached the
    prompt, and `used` of those were cited. `cited_total` counts every cited
    page, expected or not. All four count pages, not citations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    required: NonNegativeInt
    retrieved: NonNegativeInt
    used: NonNegativeInt
    cited_total: NonNegativeInt

    @model_validator(mode="after")
    def check_counts_are_consistent(self) -> Self:
        """Check that each count lies within the one it is taken from.

        The counts are sizes of nested page sets, so a larger inner count means
        `_score_answer()` counted wrong. Failing here stops a wrong score before
        it reaches the run.

        Raises:
            ValueError: When `retrieved` exceeds `required`, or `used` exceeds
                `retrieved` or `cited_total`.
        """
        if self.required < self.retrieved:
            raise ValueError(
                f"retrieved {self.retrieved} exceeds required {self.required}: "
                "a prompt page was counted that the eval set does not expect"
            )
        if self.retrieved < self.used:
            raise ValueError(
                f"used {self.used} exceeds retrieved {self.retrieved}: "
                "a cited page was counted as required though it was not in the prompt"
            )
        if self.cited_total < self.used:
            raise ValueError(
                f"used {self.used} exceeds cited_total {self.cited_total}: "
                "a page was counted as used without appearing in any statement"
            )
        return self


class GenerationResult(BaseModel):
    """What one question produced: the answer, the pages it was given, and its score.

    The full answer and the prompt pages are kept, not only the score. The ids
    in `statements` refer to `pages` in their order, and a later fact check can
    grade exactly these answers without generating them again.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    answered: bool
    statements: list[Statement]
    category: Literal["lookup", "table", "diagram", "multi-hop", "unanswerable"]
    id: str
    answered_by: str
    input_tokens: int
    output_tokens: int
    generation_seconds: float
    score: Score
    pages: list[PageRef]


class GenerationRun(BaseModel):
    """One run, with the configuration that makes its numbers comparable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_at: datetime
    commit: str | None
    eval_set_version: str
    strategy: Strategy
    k: int
    per_document: int | None = None
    candidates: int | None = None
    reranker: str | None = None
    rerank_input_tokens: int | None = None
    rerank_output_tokens: int | None = None
    embedding_model: str
    embedding_dimensions: int
    generator: str
    results: list[GenerationResult]


def _page(source: Source | ExpectedSource) -> PageRef:
    """Reduce a page to what identifies it, so pages from both sides compare equal."""
    return PageRef(document_id=source.document_id, page=source.page)


def _score_answer(question: EvalQuestion, answer: GeneratedAnswer, sources: list[Source]) -> Score:
    """Count how the required pages fared: whether they were retrieved and used.

    The counts are sizes of page sets, so a page cited by three statements
    counts once: they compare pages, not citations.

    The ids in the answer are taken as checked. `generate()` rejects any id
    outside `sources` before an answer gets here; unchecked, an id of 0 would
    quietly count the last page through `sources[0 - 1]`.
    """
    required = {_page(source) for source in question.expected_sources}
    in_prompt = {_page(source) for source in sources}
    cited = {
        _page(sources[source_id - 1])
        for statement in answer.statements
        for source_id in statement.sources
    }

    return Score(
        required=len(required),
        retrieved=len(required & in_prompt),
        used=len(required & cited),
        cited_total=len(cited),
    )


def run_generation(
    strategy: Strategy = "naive",
    *,
    k: int = 5,
    per_document: int | None = None,
    candidates: int | None = None,
    reranker: str | None = None,
    generator: str,
    runs_path: Path = DEFAULT_GENERATION_RUNS_PATH,
) -> GenerationRun:
    """Answer every eval question, score the answers, and append the run to `runs_path`.

    Each question runs the pipeline an answer would run in use: `select_pages()`,
    then `generate()` on the pages it chose. The model sees only the text of the
    question, never the eval question: its expected pages would let it copy.

    `generator` is a parameter like `reranker`, not a setting: neither model is
    tied to stored data, so each run may pick one, and comparing two is a
    matter of one argument. The embedding model is different. It made the
    vectors in the index, so it comes from the settings and is only recorded.

    A failure in any question ends the run, as in `run_retrieval()`. A run in
    the record always covers the whole eval set, so its numbers never stand on
    fewer questions than they claim.

    Raises:
        ValueError: When only one of `candidates` and `reranker` is given, or
            `candidates` is below `k`; also whatever `generate()` raises.
    """
    if (candidates is None) != (reranker is None):
        raise ValueError(
            "candidates and reranker go together: fetch that many chunks, then regrade them"
        )
    if candidates is not None and candidates < k:
        raise ValueError(f"candidates must be at least k ({k}), got {candidates}")

    eval_set = load_eval()
    settings = get_settings()
    openai_client = get_openai_client()
    anthropic_client = get_anthropic_client()

    results: list[GenerationResult] = []
    rerank_input = rerank_output = 0

    with get_connection() as conn:
        for eval_question in eval_set.questions:
            selection = select_pages(
                openai_client,
                anthropic_client,
                eval_question.question,
                conn,
                strategy,
                k=k,
                per_document=per_document,
                candidates=candidates,
                reranker=reranker,
            )
            sources = selection.pages
            rerank_input += selection.rerank_input_tokens
            rerank_output += selection.rerank_output_tokens
            generation_start = time.perf_counter()
            generated = generate(
                client=anthropic_client,
                question=eval_question.question,
                sources=sources,
                model=generator,
            )
            generation_seconds = time.perf_counter() - generation_start

            score = _score_answer(eval_question, generated.answer, sources)
            ref_pages = [_page(source) for source in sources]

            result = GenerationResult(
                answered=generated.answer.answered,
                statements=generated.answer.statements,
                category=eval_question.category,
                id=eval_question.id,
                answered_by=generated.model,
                input_tokens=generated.input_tokens,
                output_tokens=generated.output_tokens,
                generation_seconds=generation_seconds,
                score=score,
                pages=ref_pages,
            )

            results.append(result)

    run = GenerationRun(
        run_at=datetime.now(UTC),
        commit=current_commit(),
        eval_set_version=eval_set.version,
        strategy=strategy,
        k=k,
        per_document=per_document,
        candidates=candidates,
        reranker=reranker,
        # None rather than 0 without a reranker, as in `run_retrieval()`: a
        # measured zero means something else than never measured.
        rerank_input_tokens=rerank_input if reranker is not None else None,
        rerank_output_tokens=rerank_output if reranker is not None else None,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        results=results,
        generator=generator,
    )

    _log_summary(run)
    append_run(run, runs_path)

    return run


def _share(part: int, whole: int) -> str:
    """Format `part` of `whole` as a percentage with its counts, a dash for an empty whole."""
    return f"{part / whole * 100:5.1f}% ({part}/{whole})" if whole else "    — (0/0)"


def _log_summary(run: GenerationRun) -> None:
    """Log the numbers worth comparing between generation runs.

    Refusals come as two numbers, because there are two ways to get them wrong:
    answering an unanswerable question, and refusing an answerable one. Either
    alone flatters a model that always does the same thing. An unanswerable
    question that got an answer is also named, since it is the most dangerous
    outcome for someone acting on the answer.

    For the answerable questions, `used` is set against `retrieved`, not
    `required`: a page the search never delivered cannot be cited, and that
    loss belongs to retrieval, which the second number shows on its own.
    """
    results = run.results
    unanswerable = [r for r in results if r.category == "unanswerable"]
    answerable = [r for r in results if r.category != "unanswerable"]

    logger.info(
        "--- generation over %d questions, strategy '%s', k=%d, candidates=%s, "
        "reranker=%s, generator=%s ---",
        len(results),
        run.strategy,
        run.k,
        run.candidates,
        run.reranker,
        run.generator,
    )
    logger.info(
        "%-13s correct refusals %s, false refusals %s",
        "refusal",
        _share(sum(1 for r in unanswerable if not r.answered), len(unanswerable)),
        _share(sum(1 for r in answerable if not r.answered), len(answerable)),
    )
    answered_anyway = [r.id for r in unanswerable if r.answered]
    if answered_anyway:
        logger.warning("answered although unanswerable: %s", ", ".join(answered_anyway))

    per_category: dict[str, list[GenerationResult]] = collections.defaultdict(list)
    for r in answerable:
        per_category[r.category].append(r)
    for category, group in [*sorted(per_category.items()), ("ALL", answerable)]:
        used = sum(r.score.used for r in group)
        retrieved = sum(r.score.retrieved for r in group)
        required = sum(r.score.required for r in group)
        logger.info(
            "%-13s used %s of retrieved pages, retrieved %s of required, %d pages cited",
            category,
            _share(used, retrieved),
            _share(retrieved, required),
            sum(r.score.cited_total for r in group),
        )

    logger.info(
        "%-13s median generation %s; tokens generation in/out %d/%d, rerank in/out %s/%s",
        "cost",
        median_seconds([r.generation_seconds for r in results]),
        sum(r.input_tokens for r in results),
        sum(r.output_tokens for r in results),
        run.rerank_input_tokens,
        run.rerank_output_tokens,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # `Strategy` is a type hint, not a runtime check. A mistyped value would
    # filter on a strategy with no rows and fail only after the first answers
    # have been paid for.
    parser.add_argument(
        "--strategy", default="naive", choices=("naive", "advanced"), help="which index to query"
    )
    parser.add_argument("--k", type=int, default=5, help="pages the answer is generated from")
    parser.add_argument(
        "--per-document",
        type=int,
        metavar="N",
        help="chunks to keep per document, unlimited when unset",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        metavar="N",
        help="chunks to fetch before reranking, needs --reranker",
    )
    parser.add_argument(
        "--reranker",
        metavar="MODEL",
        help="model that regrades the candidates, off when unset",
    )
    # The settings supply the default only here, at the entry point; the run
    # itself takes the model as an argument and records it.
    parser.add_argument(
        "--generator",
        metavar="MODEL",
        default=get_settings().generation_model,
        help="model that writes the answers, the configured one when unset",
    )
    args = parser.parse_args()

    setup_logging()
    run_generation(
        args.strategy,
        k=args.k,
        per_document=args.per_document,
        candidates=args.candidates,
        reranker=args.reranker,
        generator=args.generator,
    )
