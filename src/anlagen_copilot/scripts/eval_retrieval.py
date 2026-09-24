"""Measures retrieval quality against the questions in `eval_set.yaml`.

Retrieval only — no generation. What is measured here is whether the pages an
answer would have to cite come back at all; whatever a model does with them
afterwards can only be worse than that ceiling.

Every run appends one line to `data/eval_runs.jsonl`. A single number says
little — the value is the series, and a series only means something if the
configuration that produced it travels alongside: a recall of 0.5 cannot be
placed without knowing `k`, the strategy and the embedding model.
"""

import argparse
import collections
import logging
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel

from anlagen_copilot.db import get_connection
from anlagen_copilot.eval import load_eval
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.paths import DATA_DIR, PROJECT_ROOT
from anlagen_copilot.rerank import rerank
from anlagen_copilot.retrieval import Source, retrieve_global, retrieve_per_document
from anlagen_copilot.settings import Strategy, get_settings

logger = logging.getLogger(__name__)

DEFAULT_EVAL_RUNS_PATH = DATA_DIR / "eval_runs.jsonl"

# What a run's numbers depend on. `data/eval_runs.jsonl` stays out on purpose:
# every run appends to it, so the second of two back-to-back runs would be marked
# dirty although only the record of the first had changed.
_CODE_PATHS = ("src", "pyproject.toml", "uv.lock")


class SourceRank(BaseModel):
    """Where one expected page landed; `None` means it was not among the pages returned."""

    document_id: str
    page: int
    retrieval_rank: int | None = None
    rerank_rank: int | None = None


class QuestionResult(BaseModel):
    """What one question produced, kept per question rather than only summed.

    The aggregates can be recomputed from these; the reverse is not true.
    Without them a later run compares as a number but not as a diff — and which
    question got worse is what actually guides the next piece of work.
    """

    id: str
    category: str
    expected: int
    found: int
    best_score: float
    retrieval_seconds: float | None = None
    rerank_seconds: float | None = None
    source_ranks: list[SourceRank] | None = None


class EvalRun(BaseModel):
    """One run, with the configuration that makes its numbers comparable."""

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
    recall: float
    results: list[QuestionResult]


def _current_commit(repo: Path = PROJECT_ROOT) -> str | None:
    """Return the short commit hash, marked `-dirty` over uncommitted code.

    A hash alone would claim a run for a commit that did not contain the code it
    ran. Only `_CODE_PATHS` count, and `status` rather than `diff`, so that a new
    module not yet added counts as well.

    `repo` rather than the working directory, because the paths are relative to
    it. None outside a repository: a missing hash makes a run harder to place
    later; failing the run over it would be worse.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *_CODE_PATHS],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    commit = head.stdout.strip()
    if not commit:
        return None
    return f"{commit}-dirty" if status.stdout.strip() else commit


def _positions(sources: list[Source]) -> dict[tuple[str, int], int]:
    """Map each page to its place from 1, so an expected page can be looked up by key."""
    return {(s.document_id, s.page): place for place, s in enumerate(sources, start=1)}


def _recall(results: list[QuestionResult]) -> float:
    """Return the found expected sources over all expected, 0.0 if none at all."""
    expected_total = sum(r.expected for r in results)
    if not expected_total:
        return 0.0
    return sum(r.found for r in results) / expected_total


def _append_run(run: EvalRun, path: Path) -> None:
    """Append one run as a single JSON line.

    One record per line is the whole point of the format, so the JSON stays
    unindented: a pretty-printed record would break every reader that goes line
    by line, and it would break silently.
    """
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json() + "\n")
    logger.info("Run appended to %s", path)


def run_retrieval(
    strategy: Strategy = "naive",
    *,
    k: int = 5,
    per_document: int | None = None,
    candidates: int | None = None,
    reranker: str | None = None,
    runs_path: Path = DEFAULT_EVAL_RUNS_PATH,
) -> EvalRun:
    """Run every eval question through retrieval and append the outcome to `runs_path`.

    One connection for the whole set: the questions are independent, and opening
    one per question would measure the connection pool rather than the retrieval.

    `per_document` picks the search: `None` measures `retrieve_global()`, the path
    the earlier runs were recorded on; a number caps each document through
    `retrieve_per_document()`. It is written into the run either way, so the two
    never mix in the series.

    `candidates` and `reranker` come as a pair: the search fetches `candidates`
    chunks, the model regrades them and keeps `k`. Both are recorded, so a
    reranked recall never passes for a plain one.

    The run is returned as well as appended, so a caller can assert on it without
    reading the file back.

    Raises:
        ValueError: When only one of `candidates` and `reranker` is given, or
            `candidates` is below `k`. Checked before the first API call.
    """
    if (candidates is None) != (reranker is None):
        raise ValueError(
            "candidates and reranker go together: fetch that many chunks, then regrade them"
        )
    if candidates is not None and candidates < k:
        raise ValueError(f"candidates must be at least k ({k}), got {candidates}")

    eval_set = load_eval()
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    anthropic_client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    fetch = k if candidates is None else candidates
    results: list[QuestionResult] = []
    rerank_input = rerank_output = 0

    with get_connection() as conn:
        for question in eval_set.questions:
            retrieval_seconds = rerank_seconds = None

            retrieval_start_time = time.perf_counter()
            if per_document is not None:
                sources = retrieve_per_document(
                    client, question.question, conn, strategy, k=fetch, per_document=per_document
                )
            else:
                sources = retrieve_global(client, question.question, conn, strategy, k=fetch)

            retrieval_end_time = time.perf_counter()
            retrieval_seconds = retrieval_end_time - retrieval_start_time
            # Taken before reranking overwrites `sources`, else the search's order is lost.
            retrieval_positions = _positions(sources)
            rerank_positions: dict[tuple[str, int], int] | None = None

            if reranker is not None:
                rerank_start_time = time.perf_counter()
                result = rerank(
                    anthropic_client, question.question, sources, model=reranker, top_n=k
                )
                rerank_end_time = time.perf_counter()

                rerank_seconds = rerank_end_time - rerank_start_time

                rerank_input += result.input_tokens
                rerank_output += result.output_tokens
                for graded in result.graded:
                    logger.debug(
                        "%s: grade %d %s p.%d",
                        question.id,
                        graded.grade,
                        graded.source.document_id,
                        graded.source.page,
                    )
                sources = [graded.source for graded in result.graded]
                rerank_positions = _positions(sources)

            for rank, s in enumerate(sources, start=1):
                logger.debug(
                    "%s: #%d %.4f %s p.%d", question.id, rank, s.score, s.document_id, s.page
                )

            expected = {(e.document_id, e.page) for e in question.expected_sources}
            source_ranks = [
                SourceRank(
                    document_id=e.document_id,
                    page=e.page,
                    retrieval_rank=retrieval_positions.get((e.document_id, e.page)),
                    rerank_rank=(
                        None
                        if rerank_positions is None
                        else rerank_positions.get((e.document_id, e.page))
                    ),
                )
                for e in question.expected_sources
            ]
            found = {(s.document_id, s.page) for s in sources}
            # The highest vector score, not the first page's: after reranking the
            # first page is the best graded one, and `best_score` would quietly
            # change its meaning between runs.
            best = max((s.score for s in sources), default=0.0)
            results.append(
                QuestionResult(
                    id=question.id,
                    category=question.category,
                    expected=len(expected),
                    found=len(expected & found),
                    best_score=best,
                    rerank_seconds=rerank_seconds,
                    retrieval_seconds=retrieval_seconds,
                    source_ranks=source_ranks,
                )
            )

            if not expected:
                # Nothing to recall here: for an unanswerable question the number
                # that matters is how close the best match came, because that is
                # what an `answered` threshold would have to sit above.
                logger.info(
                    "%s (%s): no source expected, best score %.4f",
                    question.id,
                    question.category,
                    best,
                )
            else:
                logger.info(
                    "%s (%s): %d of %d expected sources in top %d, best score %.4f",
                    question.id,
                    question.category,
                    len(expected & found),
                    len(expected),
                    len(sources),
                    best,
                )

    # None rather than 0 without a reranker: a measured zero means something else
    # than never measured, and the record is read back long after the run.
    input_tokens = rerank_input if reranker is not None else None
    output_tokens = rerank_output if reranker is not None else None

    _log_summary(
        results, strategy, k, per_document, candidates, reranker, input_tokens, output_tokens
    )

    run = EvalRun(
        run_at=datetime.now(UTC),
        commit=_current_commit(),
        eval_set_version=eval_set.version,
        strategy=strategy,
        k=k,
        per_document=per_document,
        candidates=candidates,
        reranker=reranker,
        rerank_input_tokens=input_tokens,
        rerank_output_tokens=output_tokens,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        recall=_recall(results),
        results=results,
    )
    _append_run(run, runs_path)
    return run


def _median_seconds(values: list[float]) -> str:
    """Format the median, or a dash when nothing was timed — `median([])` raises."""
    return f"{statistics.median(values):.2f}s" if values else "—"


def _log_summary(
    results: list[QuestionResult],
    strategy: Strategy,
    k: int,
    per_document: int | None,
    candidates: int | None,
    reranker: str | None,
    rerank_input_tokens: int | None,
    rerank_output_tokens: int | None,
) -> None:
    """Aggregate the per-question outcomes into the numbers worth comparing.

    Recall and hit rate answer different questions and stay apart: recall gives
    partial credit, so a multi-hop question with one of two sources found counts
    a half, while the hit rate only asks whether anything usable came back at
    all. Both are broken down by category, because averaging `lookup` and
    `diagram` into one number hides what the eval set was built to show.
    """
    per_category: dict[str, list[QuestionResult]] = collections.defaultdict(list)
    for r in results:
        if r.expected:
            per_category[r.category].append(r)

    logger.info(
        "--- retrieval over %d questions, strategy '%s', k=%d, per_document=%s, "
        "candidates=%s, reranker=%s, rerank tokens in/out %s/%s ---",
        len(results),
        strategy,
        k,
        per_document,
        candidates,
        reranker,
        rerank_input_tokens,
        rerank_output_tokens,
    )

    for category in sorted(per_category):
        group = per_category[category]
        expected_total = sum(r.expected for r in group)
        found_total = sum(r.found for r in group)
        hits = sum(1 for r in group if r.found)
        logger.info(
            "%-13s recall %5.1f%% (%d/%d sources), hit rate %5.1f%% (%d/%d questions)",
            category,
            found_total / expected_total * 100,
            found_total,
            expected_total,
            hits / len(group) * 100,
            hits,
            len(group),
        )

    answerable = [r for r in results if r.expected]
    logger.info(
        "%-13s recall %5.1f%% (%d/%d sources)",
        "ALL",
        _recall(results) * 100,
        sum(r.found for r in answerable),
        sum(r.expected for r in answerable),
    )

    # Medians, not means: one stalled API call would drag a mean along. The total
    # is summed per question first, because that sum is what a user waits for.
    retrieval = [r.retrieval_seconds for r in results if r.retrieval_seconds is not None]
    reranking = [r.rerank_seconds for r in results if r.rerank_seconds is not None]
    per_question = [
        r.retrieval_seconds + (r.rerank_seconds if r.rerank_seconds is not None else 0.0)
        for r in results
        if r.retrieval_seconds is not None
    ]
    logger.info(
        "%-13s median per question: retrieval %s, rerank %s, total %s",
        "latency",
        _median_seconds(retrieval),
        _median_seconds(reranking),
        _median_seconds(per_question),
    )

    # The unanswerable questions are the only ones that say where an `answered`
    # threshold could sit: if the best score they reach stays below the weakest
    # score of a question that did find its source, the two ranges do not
    # overlap and the threshold can be measured instead of guessed.
    unanswerable_best = [r.best_score for r in results if not r.expected]
    hit_best = [r.best_score for r in answerable if r.found]
    if unanswerable_best and hit_best:
        logger.info(
            "threshold: unanswerable peak %.4f, weakest hit %.4f — %s",
            max(unanswerable_best),
            min(hit_best),
            "separable" if max(unanswerable_best) < min(hit_best) else "overlapping",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # `Strategy` is a type hint, not a runtime check. A mistyped value would
    # filter on a strategy with no rows, score a recall of 0.0, and fail only
    # when pydantic builds the `EvalRun` — after all 36 questions have been
    # embedded and queried.
    parser.add_argument(
        "--strategy", default="naive", choices=("naive", "advanced"), help="which index to query"
    )
    parser.add_argument("--k", type=int, default=5, help="chunks to retrieve per question")
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
    args = parser.parse_args()

    setup_logging()
    run_retrieval(
        args.strategy,
        k=args.k,
        per_document=args.per_document,
        candidates=args.candidates,
        reranker=args.reranker,
    )
