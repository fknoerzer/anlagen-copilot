import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from unittest.mock import Mock

import pytest
from helpers import make_answer, make_eval_question, was_logged

from anlagen_copilot.eval import EvalQuestion, EvalSet
from anlagen_copilot.factcheck import FactCheck, FactVerdict
from anlagen_copilot.runlog import append_run, load_runs
from anlagen_copilot.scripts import eval_facts
from anlagen_copilot.scripts.eval_facts import (
    FactCheckResult,
    FactCheckRun,
    _log_summary,
    _select_run,
    run_fact_check,
)
from anlagen_copilot.scripts.eval_generate import GenerationResult, GenerationRun, PageRef, Score

_FIRST = datetime(2026, 10, 19, 11, 54, tzinfo=UTC)
_SECOND = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_THIRD = datetime(2026, 10, 19, 12, 8, tzinfo=UTC)


def _result(question_id: str = "q-test", *, answered: bool = True) -> GenerationResult:
    category: Literal["lookup", "unanswerable"] = (
        "unanswerable" if question_id == "q-none" else "lookup"
    )
    return GenerationResult(
        answered=answered,
        statements=make_answer(answered, ("Wert A", [1] if answered else [])).statements,
        category=category,
        id=question_id,
        answered_by="answering-model",
        input_tokens=6000,
        output_tokens=200,
        generation_seconds=1.0,
        score=Score(required=1, retrieved=1, used=1, cited_total=1),
        pages=[PageRef(document_id="sew-getriebe-ba", page=1)],
    )


def _run(
    run_at: datetime = _FIRST,
    *,
    version: str = "v-test",
    commit: str = "abc1234",
    results: list[GenerationResult] | None = None,
) -> GenerationRun:
    return GenerationRun(
        run_at=run_at,
        commit=commit,
        eval_set_version=version,
        strategy="naive",
        k=5,
        embedding_model="test-embedding-model",
        embedding_dimensions=4,
        generator="test-generator",
        results=[_result()] if results is None else results,
    )


def _unanswerable() -> EvalQuestion:
    return make_eval_question(
        id="q-none", category="unanswerable", expected_sources=[], required_facts=[]
    )


def _fact_check(*verdicts: tuple[str, str]) -> FactCheck:
    """A judge's reply from (fact, verdict) pairs."""
    return FactCheck(
        checked=[
            FactVerdict.model_validate({"fact": fact, "reason": "Begründung.", "verdict": verdict})
            for fact, verdict in verdicts
        ],
        model="judging-model",
        input_tokens=1500,
        output_tokens=300,
    )


def _patch_run_fact_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    questions: list[EvalQuestion],
    runs: list[GenerationRun],
    check: Mock,
) -> tuple[Path, Mock]:
    """Writes `runs` to a record, patches the eval set and the judge; returns record and client.

    The runs go through `append_run()` and are read back by the real
    `load_runs()`, so the test covers the record the script reads in use.
    """
    runs_path = tmp_path / "generation.jsonl"
    for run in runs:
        append_run(run, runs_path)
    client = Mock()
    monkeypatch.setattr(
        eval_facts, "load_eval", Mock(return_value=EvalSet(version="v-test", questions=questions))
    )
    monkeypatch.setattr(eval_facts, "get_anthropic_client", Mock(return_value=client))
    monkeypatch.setattr(eval_facts, "check_facts", check)
    return runs_path, client


def test_select_run_takes_the_newest_run_without_a_prefix() -> None:
    runs = [_run(_SECOND), _run(_THIRD), _run(_FIRST)]

    assert _select_run(runs, version="v-test", run_at_prefix=None).run_at == _THIRD


def test_select_run_takes_the_one_run_the_prefix_names() -> None:
    runs = [_run(_FIRST), _run(_SECOND), _run(_THIRD)]

    assert _select_run(runs, version="v-test", run_at_prefix="2026-10-19T12:00").run_at == _SECOND


def test_select_run_rejects_a_prefix_that_names_several_runs() -> None:
    """The first of several would be a guess at which answers get judged."""
    runs = [_run(_FIRST), _run(_SECOND), _run(_THIRD)]

    with pytest.raises(ValueError, match="'2026-10-19T12' matches 2 runs"):
        _select_run(runs, version="v-test", run_at_prefix="2026-10-19T12")


def test_select_run_lists_the_runs_when_the_prefix_names_none() -> None:
    runs = [_run(_FIRST), _run(_SECOND)]

    with pytest.raises(ValueError, match="matches 0 runs") as raised:
        _select_run(runs, version="v-test", run_at_prefix="2027")

    assert _FIRST.isoformat() in str(raised.value)
    assert _SECOND.isoformat() in str(raised.value)


def test_select_run_does_not_reach_a_run_on_another_eval_set() -> None:
    """Its answers were given to other questions; their ids may match and mean something else."""
    runs = [_run(_FIRST, version="v-old"), _run(_THIRD)]

    with pytest.raises(ValueError, match="matches 0 runs"):
        _select_run(runs, version="v-test", run_at_prefix="2026-10-19T11:54")


def test_select_run_names_the_versions_when_none_matches() -> None:
    runs = [_run(version="v-old")]

    with pytest.raises(
        ValueError, match=r"no generation run on eval set v-test, only on \['v-old'\]"
    ):
        _select_run(runs, version="v-test", run_at_prefix=None)


def test_run_fact_check_records_the_verdicts_on_a_judged_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = make_eval_question(question="Wie oft Lager prüfen?", required_facts=["Fakt A."])
    check = Mock(return_value=_fact_check(("Fakt A.", "present")))
    runs_path, client = _patch_run_fact_check(monkeypatch, tmp_path, [question], [_run()], check)

    run = run_fact_check(
        judge="judging-model", runs_path=runs_path, facts_path=tmp_path / "f.jsonl"
    )

    result = run.results[0]
    assert result.complete is True
    assert result.facts == _fact_check(("Fakt A.", "present")).checked
    assert (result.judged_by, result.input_tokens, result.output_tokens) == (
        "judging-model",
        1500,
        300,
    )
    # The judge sees the question text and the stored answer, and is the one asked for.
    assert check.call_args.args == (
        client,
        "Wie oft Lager prüfen?",
        make_answer(True, ("Wert A", [1])),
        ["Fakt A."],
    )
    assert check.call_args.kwargs == {"model": "judging-model"}


def test_run_fact_check_marks_an_answer_with_a_missing_fact_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = make_eval_question(required_facts=["Fakt A.", "Fakt B."])
    check = Mock(return_value=_fact_check(("Fakt A.", "present"), ("Fakt B.", "missing")))
    runs_path, _ = _patch_run_fact_check(monkeypatch, tmp_path, [question], [_run()], check)

    run = run_fact_check(
        judge="judging-model", runs_path=runs_path, facts_path=tmp_path / "f.jsonl"
    )

    assert run.results[0].complete is False


def test_run_fact_check_records_but_does_not_judge_refusals_and_unanswerable_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipped, not dropped: a question missing from the record would look like one never asked."""
    results = [_result("q-test", answered=False), _result("q-none", answered=True)]
    check = Mock()
    runs_path, _ = _patch_run_fact_check(
        monkeypatch,
        tmp_path,
        [make_eval_question(), _unanswerable()],
        [_run(results=results)],
        check,
    )

    run = run_fact_check(
        judge="judging-model", runs_path=runs_path, facts_path=tmp_path / "f.jsonl"
    )

    check.assert_not_called()
    assert run.results == [
        FactCheckResult(id="q-test", category="lookup"),
        FactCheckResult(id="q-none", category="unanswerable"),
    ]


def test_run_fact_check_names_the_judged_run_and_appends_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = Mock(return_value=_fact_check(("Testfakt.", "present")))
    runs_path, _ = _patch_run_fact_check(
        monkeypatch,
        tmp_path,
        [make_eval_question()],
        [_run(_FIRST, commit="aaa1111"), _run(_THIRD, commit="ccc3333")],
        check,
    )
    facts_path = tmp_path / "facts" / "eval_runs.jsonl"

    run = run_fact_check(judge="judging-model", runs_path=runs_path, facts_path=facts_path)

    assert (run.judged_run_at, run.judged_commit) == (_THIRD, "ccc3333")
    assert (run.judge, run.eval_set_version) == ("judging-model", "v-test")
    assert load_runs(facts_path, FactCheckRun) == [run]


def test_run_fact_check_rejects_an_answer_to_a_question_not_in_the_eval_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 005: an answer without its question fails the check instead of being skipped."""
    check = Mock()
    runs_path, _ = _patch_run_fact_check(
        monkeypatch, tmp_path, [make_eval_question()], [_run(results=[_result("q-gone")])], check
    )
    facts_path = tmp_path / "f.jsonl"

    with pytest.raises(ValueError, match="answered q-gone, which eval set v-test does not contain"):
        run_fact_check(judge="judging-model", runs_path=runs_path, facts_path=facts_path)

    check.assert_not_called()
    assert not facts_path.exists()


def test_run_fact_check_fails_on_an_unknown_run_before_creating_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mistyped prefix must not cost anything; the client stands for the first paid step."""
    runs_path, _ = _patch_run_fact_check(
        monkeypatch, tmp_path, [make_eval_question()], [_run()], Mock()
    )
    get_client = Mock()
    monkeypatch.setattr(eval_facts, "get_anthropic_client", get_client)

    with pytest.raises(ValueError, match="matches 0 runs"):
        run_fact_check(
            run_at_prefix="2027",
            judge="judging-model",
            runs_path=runs_path,
            facts_path=tmp_path / "f.jsonl",
        )

    get_client.assert_not_called()


def test_run_fact_check_names_the_question_a_judge_error_came_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = Mock(side_effect=ValueError("no verdict for Testfakt."))
    runs_path, _ = _patch_run_fact_check(
        monkeypatch, tmp_path, [make_eval_question()], [_run()], check
    )
    facts_path = tmp_path / "f.jsonl"

    with pytest.raises(ValueError, match="no verdict for") as raised:
        run_fact_check(judge="judging-model", runs_path=runs_path, facts_path=facts_path)

    assert raised.value.__notes__ == ["while judging q-test (lookup)"]
    assert not facts_path.exists()


def test_log_summary_counts_complete_answers_among_the_judged_and_names_a_contradiction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refusal is the generation summary's loss; counted here, it would count twice."""
    judged = FactCheckResult(
        id="q-a",
        category="lookup",
        facts=_fact_check(("Fakt A.", "contradicted")).checked,
        complete=False,
        judge_seconds=2.0,
        input_tokens=1500,
        output_tokens=300,
    )
    refused = FactCheckResult(id="q-b", category="lookup")
    run = FactCheckRun(
        run_at=_THIRD,
        commit="abc1234",
        eval_set_version="v-test",
        judge="judging-model",
        judged_run_at=_FIRST,
        judged_commit="aaa1111",
        results=[judged, refused],
    )

    with caplog.at_level(logging.INFO):
        _log_summary(run)

    assert was_logged(caplog, logging.INFO, "fact check over 1 of 2 answers"), caplog.text
    assert was_logged(caplog, logging.INFO, "complete   0.0% (0/1)"), caplog.text
    assert was_logged(caplog, logging.WARNING, "q-a contradicts 'Fakt A.'"), caplog.text
