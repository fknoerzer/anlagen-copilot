"""Check stored generation answers against the required facts of the eval set.

The second half of the answer evaluation: `eval_generate.py` scores an answer
by the pages it cites, this script by what it says. A separate model judges
each answer of one recorded generation run, so the answers are graded as they
were given and nothing is generated again.
"""

import argparse
import collections
import logging
import operator
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from anlagen_copilot.clients import get_anthropic_client
from anlagen_copilot.eval import load_eval
from anlagen_copilot.factcheck import FactVerdict, all_facts_present, check_facts
from anlagen_copilot.generate import GeneratedAnswer
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.paths import DATA_DIR
from anlagen_copilot.runlog import append_run, current_commit, load_runs, median_seconds
from anlagen_copilot.scripts.eval_generate import DEFAULT_GENERATION_RUNS_PATH, GenerationRun
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_FACT_RUNS_PATH = DATA_DIR / "facts/eval_runs.jsonl"


class FactCheckResult(BaseModel):
    """The verdicts on one stored answer, and what the judge spent on them.

    A refusal is recorded but not judged: `facts`, `complete` and the judge
    fields stay None, so a skipped question is visible as skipped rather than
    missing from the run. The same holds for an answer to an unanswerable
    question, which has no facts to check.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    category: Literal["lookup", "table", "diagram", "multi-hop", "unanswerable"]
    facts: list[FactVerdict] | None = None
    complete: bool | None = None
    judged_by: str | None = None
    judge_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class FactCheckRun(BaseModel):
    """One fact check over one generation run, which it names instead of copying.

    The judged run is identified by its `run_at` and commit; its configuration
    stays in its own record. Copied here, it would have to come from that record
    and not from the settings of today, which may have changed since.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_at: datetime
    commit: str | None
    eval_set_version: str
    judge: str
    judged_run_at: datetime
    judged_commit: str | None
    results: list[FactCheckResult]


def _select_run(
    runs: list[GenerationRun], *, version: str, run_at_prefix: str | None
) -> GenerationRun:
    """Pick the generation run to judge: the newest on `version`, or the one `run_at_prefix` names.

    Only runs on the loaded eval set qualify, before the prefix is applied: their
    answers were given to the questions whose facts are checked, and a prefix
    that happens to match a run on another version must not reach it. A prefix
    has to name exactly one run; the first of several would be a guess.

    Raises:
        ValueError: When no run is on `version`, or the prefix matches no run or
            more than one. The message lists the runs to choose from.
    """
    runs_with_correct_version = [run for run in runs if run.eval_set_version == version]

    if not runs_with_correct_version:
        versions = sorted({run.eval_set_version for run in runs})
        raise ValueError(f"no generation run on eval set {version}, only on {versions}")

    if run_at_prefix is None:
        return max(runs_with_correct_version, key=operator.attrgetter("run_at"))

    matches = [
        run for run in runs_with_correct_version if run.run_at.isoformat().startswith(run_at_prefix)
    ]
    if len(matches) != 1:
        candidates = [run.run_at.isoformat() for run in (matches or runs_with_correct_version)]
        raise ValueError(
            f"{run_at_prefix!r} matches {len(matches)} runs on eval set {version}; "
            f"choose one of {candidates}"
        )
    return matches[0]


def run_fact_check(
    *,
    run_at_prefix: str | None = None,
    judge: str,
    runs_path: Path = DEFAULT_GENERATION_RUNS_PATH,
    facts_path: Path = DEFAULT_FACT_RUNS_PATH,
) -> FactCheckRun:
    """Judge every answer of one generation run and append the check to `facts_path`.

    The run is chosen before the client is created, so a mistyped prefix fails
    before anything is paid. `judge` is a parameter like the generator in
    `run_generation()`: the judge is tied to no stored data, and comparing two
    judges on the same answers is a matter of one argument.

    Only answers to answerable questions are judged. A refusal has no
    statements to check, and an answer to an unanswerable question has no facts
    to check it against; the generation summary already names that case.

    A failure in any question ends the check, as in `run_generation()`, so a
    recorded check always covers the whole run.

    Raises:
        ValueError: When `_select_run()` finds no run to judge, or the run
            answered a question the eval set does not contain; also whatever
            `check_facts()` raises.
    """
    eval_set = load_eval()
    runs = load_runs(runs_path, GenerationRun)
    run = _select_run(runs, version=eval_set.version, run_at_prefix=run_at_prefix)
    logger.info("judging the generation run of %s (%s)", run.run_at.isoformat(), run.commit)

    anthropic_client = get_anthropic_client()
    questions_by_id = {question.id: question for question in eval_set.questions}
    results: list[FactCheckResult] = []

    for result in run.results:
        if result.id not in questions_by_id:
            raise ValueError(
                f"the generation run of {run.run_at.isoformat()} answered {result.id}, "
                f"which eval set {eval_set.version} does not contain"
            )
        question = questions_by_id[result.id]

        if not result.answered or question.category == "unanswerable":
            logger.info("%s (%s): not judged", result.id, result.category)
            results.append(FactCheckResult(id=result.id, category=result.category))
            continue

        answer = GeneratedAnswer(answered=result.answered, statements=result.statements)
        judge_start = time.perf_counter()
        try:
            fact_check = check_facts(
                anthropic_client,
                question.question,
                answer,
                question.required_facts,
                model=judge,
            )
        except Exception as e:
            e.add_note(f"while judging {result.id} ({result.category})")
            raise
        judge_seconds = time.perf_counter() - judge_start

        complete = all_facts_present(fact_check.checked)
        logger.info(
            "%s (%s): %s, %d/%d tokens, %.1fs",
            result.id,
            result.category,
            "complete" if complete else "incomplete",
            fact_check.input_tokens,
            fact_check.output_tokens,
            judge_seconds,
        )
        results.append(
            FactCheckResult(
                id=result.id,
                category=result.category,
                facts=fact_check.checked,
                complete=complete,
                judged_by=fact_check.model,
                judge_seconds=judge_seconds,
                input_tokens=fact_check.input_tokens,
                output_tokens=fact_check.output_tokens,
            )
        )

    fact_check_run = FactCheckRun(
        run_at=datetime.now(UTC),
        commit=current_commit(),
        eval_set_version=eval_set.version,
        judge=judge,
        judged_run_at=run.run_at,
        judged_commit=run.commit,
        results=results,
    )

    _log_summary(fact_check_run)
    append_run(fact_check_run, facts_path)

    return fact_check_run


def _log_summary(run: FactCheckRun) -> None:
    """Log the numbers worth comparing between fact checks.

    Complete answers are counted per category against the judged answers, not
    against all questions: a refusal is a loss the generation summary already
    counts. Contradicted facts are named one by one, since an answer that says
    the wrong thing is worse for someone acting on it than one that leaves a
    fact out.
    """
    judged = [r for r in run.results if r.facts is not None]

    logger.info(
        "--- fact check over %d of %d answers, judge=%s, generation run %s ---",
        len(judged),
        len(run.results),
        run.judge,
        run.judged_run_at.isoformat(),
    )

    per_category: dict[str, list[FactCheckResult]] = collections.defaultdict(list)
    for r in judged:
        per_category[r.category].append(r)
    for category, group in [*sorted(per_category.items()), ("ALL", judged)]:
        complete = sum(1 for r in group if r.complete)
        logger.info(
            "%-13s complete %5.1f%% (%d/%d)",
            category,
            complete / len(group) * 100 if group else 0.0,
            complete,
            len(group),
        )

    verdicts = collections.Counter(v.verdict for r in judged for v in r.facts or [])
    logger.info(
        "%-13s present %d, missing %d, contradicted %d",
        "facts",
        verdicts["present"],
        verdicts["missing"],
        verdicts["contradicted"],
    )
    for r in judged:
        for v in r.facts or []:
            if v.verdict == "contradicted":
                logger.warning("%s contradicts %r: %s", r.id, v.fact, v.reason)

    logger.info(
        "%-13s median judge %s; tokens in/out %d/%d",
        "cost",
        median_seconds([r.judge_seconds for r in judged if r.judge_seconds is not None]),
        sum(r.input_tokens or 0 for r in judged),
        sum(r.output_tokens or 0 for r in judged),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-at",
        metavar="PREFIX",
        help="start of the run_at of the generation run to judge, the newest when unset",
    )
    # As with --generator in `eval_generate.py`, the settings supply the
    # default only here, at the entry point.
    parser.add_argument(
        "--judge",
        metavar="MODEL",
        default=get_settings().judge_model,
        help="model that judges the answers, the configured one when unset",
    )
    args = parser.parse_args()

    setup_logging()
    run_fact_check(run_at_prefix=args.run_at, judge=args.judge)
