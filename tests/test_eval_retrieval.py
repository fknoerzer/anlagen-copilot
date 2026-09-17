import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, call

import pytest
from helpers import make_eval_question

from anlagen_copilot.eval import EvalQuestion, EvalSet
from anlagen_copilot.retrieval import Source
from anlagen_copilot.scripts import eval_retrieval
from anlagen_copilot.scripts.eval_retrieval import (
    EvalRun,
    QuestionResult,
    _append_run,
    _current_commit,
    _recall,
    run_retrieval,
)


def _raise(exc: Exception) -> object:
    """Builds a `subprocess.run` stand-in that fails with `exc`."""

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise exc

    return run


def _make_question_result(**overrides: object) -> QuestionResult:
    """Builds a valid QuestionResult, mandatory fields as placeholders.

    `expected` and `found` belong at the call site of every recall assertion:
    they are what the number under test is computed from, and a default taking
    part in that arithmetic from over here makes the expected value unreadable.
    They carry defaults anyway, so that a test about something else — a
    category, a score — does not have to spell them out.
    """
    defaults: dict[str, object] = {
        "id": "q-test",
        "category": "lookup",
        "expected": 1,
        "found": 1,
        "best_score": 0.7,
    }
    defaults.update(overrides)
    return QuestionResult.model_validate(defaults)


def _make_eval_run(**overrides: object) -> EvalRun:
    """Builds a valid EvalRun, mandatory fields as placeholders.

    `recall` and `results` are independent fields — nothing in the model ties
    the number to the entries. The defaults are picked to agree anyway (one
    question, one of two sources found, 0.5), so that a record read out of a
    test file does not look impossible.
    """
    defaults: dict[str, object] = {
        "run_at": datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
        "commit": "abc1234",
        "strategy": "naive",
        "k": 5,
        "embedding_model": "test-embedding-model",
        "embedding_dimensions": 4,
        "recall": 0.5,
        "results": [_make_question_result(expected=2, found=1)],
    }
    defaults.update(overrides)
    return EvalRun.model_validate(defaults)


def _make_source(**overrides: object) -> Source:
    """Builds a Source as retrieval hands it back — the five enrichment fields stay None.

    `document_id` and `page` belong at the call site: they are what the set
    arithmetic in `run_retrieval()` matches against `expected_sources`, so a
    default here would hide what makes a question a hit or a miss.
    """
    defaults: dict[str, object] = {
        "document_id": "sew-getriebe-ba",
        "page": 1,
        "score": 0.7,
        "content": "Seiteninhalt",
    }
    defaults.update(overrides)
    return Source.model_validate(defaults)


def _patch_run_retrieval(
    monkeypatch: pytest.MonkeyPatch, questions: list[EvalQuestion], results: list[list[Source]]
) -> Mock:
    """Replaces everything `run_retrieval()` reaches outside itself; returns the search mock.

    `results` holds one list per question, in order: the search is called once for
    each, and `side_effect` hands them out in turn. A list of the wrong length
    fails with StopIteration instead of reusing a result.

    Both retrieval functions get the same mock, so a test picks the path through
    `per_document` and reads the calls off one object either way.

    Settings stay real — `conftest` provides them, and `run_retrieval()` records
    them in the run, which a mock would only echo back.
    """
    eval_set = EvalSet(questions=questions)
    monkeypatch.setattr(eval_retrieval, "load_eval", Mock(return_value=eval_set))
    monkeypatch.setattr(eval_retrieval, "OpenAI", Mock())
    monkeypatch.setattr(eval_retrieval, "get_connection", MagicMock())
    retrieve = Mock(side_effect=results)
    monkeypatch.setattr(eval_retrieval, "retrieve_global", retrieve)
    monkeypatch.setattr(eval_retrieval, "retrieve_per_document", retrieve)
    return retrieve


def test_current_commit_returns_the_short_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout="27f3503\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)

    assert _current_commit() == "27f3503"


def test_current_commit_is_none_outside_a_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _raise(subprocess.CalledProcessError(128, "git")))

    assert _current_commit() is None


def test_current_commit_is_none_when_git_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _raise(FileNotFoundError("git")))

    assert _current_commit() is None


def test_recall_is_one_when_every_source_is_found() -> None:
    results = [
        _make_question_result(expected=1, found=1),
        _make_question_result(expected=2, found=2),
    ]

    assert _recall(results) == 1.0


def test_recall_is_zero_when_no_source_is_expected() -> None:
    results = [_make_question_result(expected=0, found=0)]

    assert _recall(results) == 0.0


def test_recall_sums_sources_before_dividing() -> None:
    results = [
        _make_question_result(expected=1, found=1),
        _make_question_result(expected=2, found=1),
    ]

    assert _recall(results) == 2 / 3


def test_append_run_keeps_the_earlier_run(tmp_path: Path) -> None:
    path = tmp_path / "eval_runs.jsonl"

    first_run = _make_eval_run(commit="aaa1111")
    second_run = _make_eval_run(commit="bbb2222")

    _append_run(first_run, path)
    _append_run(second_run, path)

    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert [EvalRun.model_validate_json(line) for line in lines] == [first_run, second_run]


def test_append_run_round_trips_non_ascii(tmp_path: Path) -> None:
    path = tmp_path / "eval_runs.jsonl"

    run = _make_eval_run(embedding_model="mödél")

    _append_run(run, path)

    lines = path.read_text(encoding="utf-8").splitlines()

    assert [EvalRun.model_validate_json(line) for line in lines] == [run]


def test_run_retrieval_scores_each_question_against_its_expected_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two questions, one hit and one miss, through the whole orchestration.

    Asserted on the returned run, as the docstring of `run_retrieval()` intends;
    the file is checked once at the end, because returning a run it never wrote
    would satisfy everything above.
    """
    runs_path = tmp_path / "eval_runs.jsonl"
    _patch_run_retrieval(
        monkeypatch,
        [make_eval_question(id="q-1"), make_eval_question(id="q-2")],
        [[_make_source(page=1, score=0.7)], [_make_source(page=99, score=0.4)]],
    )

    run = run_retrieval(strategy="naive", runs_path=runs_path)

    assert [(r.id, r.expected, r.found, r.best_score) for r in run.results] == [
        ("q-1", 1, 1, 0.7),
        ("q-2", 1, 0, 0.4),
    ]
    assert run.recall == 0.5
    assert EvalRun.model_validate_json(runs_path.read_text(encoding="utf-8").strip()) == run


def test_run_retrieval_leaves_the_recall_alone_for_an_unanswerable_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unanswerable question is recorded with its best score but moves no number.

    With `expected` at 0 it adds to neither side of the fraction, so the recall
    of the other two stays at 0.5. `_log_summary()` relies on this: it passes
    every result to `_recall()` but prints its fractions over the answerable ones.
    """
    _patch_run_retrieval(
        monkeypatch,
        [
            make_eval_question(id="q-1"),
            make_eval_question(id="q-2"),
            make_eval_question(
                id="q-3", category="unanswerable", expected_sources=[], expected_facts=[]
            ),
        ],
        [[_make_source(page=1)], [_make_source(page=99)], [_make_source(page=5, score=0.6)]],
    )

    run = run_retrieval(strategy="naive", runs_path=tmp_path / "eval_runs.jsonl")

    unanswerable = run.results[2]
    assert (unanswerable.expected, unanswerable.found, unanswerable.best_score) == (0, 0, 0.6)
    assert run.recall == 0.5


def test_run_retrieval_searches_with_the_k_and_strategy_it_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`k` and `strategy` appear twice: in the search call and in the run.

    Dropped from the call, every run would search with the defaults while still
    recording the arguments — a measurement series that misstates its own
    configuration, and nothing fails. Hence non-default values on both.
    """
    retrieve = _patch_run_retrieval(monkeypatch, [make_eval_question()], [[_make_source()]])

    run = run_retrieval(strategy="advanced", k=20, runs_path=tmp_path / "eval_runs.jsonl")

    assert retrieve.call_args == call(ANY, "Testfrage?", ANY, "advanced", k=20)
    assert (run.strategy, run.k) == ("advanced", 20)


def test_run_retrieval_scores_zero_when_retrieval_returns_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rows for the strategy, as in the first advanced run before any advanced ingest.

    `sources[0]` would raise there, after the embedding calls have been paid for.
    The question is recorded as having found nothing, with a best score of 0.0.
    """
    _patch_run_retrieval(monkeypatch, [make_eval_question()], [[]])

    run = run_retrieval(strategy="naive", runs_path=tmp_path / "eval_runs.jsonl")

    assert (run.results[0].found, run.results[0].best_score) == (0, 0.0)
