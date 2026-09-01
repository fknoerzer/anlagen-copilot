"""Measures retrieval quality against the questions in `eval_set.yaml`.

Retrieval only — no generation. What is measured here is whether the pages an
answer would have to cite come back at all; whatever a model does with them
afterwards can only be worse than that ceiling.

Every run appends one line to `data/eval_runs.jsonl`. A single number says
little — the value is the series, and a series only means something if the
configuration that produced it travels alongside: a recall of 0.5 cannot be
placed without knowing `k`, the strategy and the embedding model.
"""

import collections
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from anlagen_copilot.db import get_connection
from anlagen_copilot.eval import load_eval
from anlagen_copilot.paths import DATA_DIR
from anlagen_copilot.retrieval import retrieve
from anlagen_copilot.settings import Strategy, get_settings

logger = logging.getLogger(__name__)

DEFAULT_EVAL_RUNS_PATH = DATA_DIR / "eval_runs.jsonl"


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


class EvalRun(BaseModel):
    """One run, with the configuration that makes its numbers comparable."""

    run_at: datetime
    commit: str | None
    strategy: Strategy
    k: int
    embedding_model: str
    embedding_dimensions: int
    recall: float
    results: list[QuestionResult]


def _current_commit() -> str | None:
    """Short commit hash, or None outside a repository — never fatal.

    A missing hash makes a run harder to place later; failing the run over it
    would be worse.
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return done.stdout.strip() or None


def _recall(results: list[QuestionResult]) -> float:
    """Found expected sources over all expected sources, 0.0 if none are expected."""
    expected_total = sum(r.expected for r in results)
    if not expected_total:
        return 0.0
    return sum(r.found for r in results) / expected_total


def _append_run(run: EvalRun, path: Path) -> None:
    """Appends one run as a single JSON line.

    One record per line is the whole point of the format, so the JSON stays
    unindented: a pretty-printed record would break every reader that goes line
    by line, and it would break silently.
    """
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json() + "\n")
    logger.info("Run appended to %s", path)


def run_retrieval(
    strategy: Strategy = "naive", *, k: int = 5, runs_path: Path = DEFAULT_EVAL_RUNS_PATH
) -> EvalRun:
    eval_set = load_eval()
    client = OpenAI(api_key=get_settings().openai_api_key.get_secret_value())
    results: list[QuestionResult] = []

    with get_connection() as conn:
        for question in eval_set.questions:
            sources = retrieve(client, question.question, conn, strategy, k=k)

            for rank, s in enumerate(sources, start=1):
                logger.debug(
                    "%s: #%d %.4f %s p.%d", question.id, rank, s.score, s.document_id, s.page
                )

            expected = {(e.document_id, e.page) for e in question.expected_sources}
            found = {(s.document_id, s.page) for s in sources}
            best = sources[0].score if sources else 0.0
            results.append(
                QuestionResult(
                    id=question.id,
                    category=question.category,
                    expected=len(expected),
                    found=len(expected & found),
                    best_score=best,
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

    _log_summary(results, strategy, k)

    settings = get_settings()
    run = EvalRun(
        run_at=datetime.now(UTC),
        commit=_current_commit(),
        strategy=strategy,
        k=k,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        recall=_recall(results),
        results=results,
    )
    _append_run(run, runs_path)
    return run


def _log_summary(results: list[QuestionResult], strategy: Strategy, k: int) -> None:
    """Aggregates the per-question outcomes into the numbers worth comparing.

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
        "--- retrieval over %d questions, strategy '%s', k=%d ---", len(results), strategy, k
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
