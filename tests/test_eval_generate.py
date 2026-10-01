import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from helpers import make_eval_question, was_logged
from pydantic import ValidationError

from anlagen_copilot.eval import EvalQuestion, EvalSet
from anlagen_copilot.generate import Generated, GeneratedAnswer
from anlagen_copilot.pipeline import PageSelection
from anlagen_copilot.retrieval import Source
from anlagen_copilot.scripts import eval_generate
from anlagen_copilot.scripts.eval_generate import (
    GenerationResult,
    GenerationRun,
    PageRef,
    Score,
    _log_summary,
    _score_answer,
    run_generation,
)


def _source(page: int, document_id: str = "sew-getriebe-ba") -> Source:
    return Source(document_id=document_id, page=page, score=0.5, content=f"Seite {page}")


def _answer(answered: bool, *statements: tuple[str, list[int]]) -> GeneratedAnswer:
    return GeneratedAnswer.model_validate(
        {
            "answered": answered,
            "statements": [{"text": text, "sources": ids} for text, ids in statements],
        }
    )


def _question(**overrides: object) -> EvalQuestion:
    """An answerable question whose one expected page is `sew-getriebe-ba` p. 1."""
    return make_eval_question(**overrides)


def _unanswerable(**overrides: object) -> EvalQuestion:
    defaults: dict[str, object] = {
        "id": "q-none",
        "category": "unanswerable",
        "expected_sources": [],
        "expected_facts": [],
    }
    defaults.update(overrides)
    return make_eval_question(**defaults)


def test_score_answer_counts_a_page_cited_for_an_unanswerable_question() -> None:
    """Answering what the manuals do not cover is the dangerous case; `cited_total` shows it."""
    score = _score_answer(_unanswerable(), _answer(True, ("Wert A", [1])), [_source(7)])

    assert score == Score(required=0, retrieved=0, used=0, cited_total=1)


def test_score_answer_follows_the_required_pages_to_the_answer() -> None:
    """Like q-007: one of two required pages retrieved and used, plus two pages not required."""
    question = _question(
        expected_sources=[
            {"document_id": "sew-getriebe-ba", "page": 70},
            {"document_id": "sew-schmierstoffe", "page": 7},
        ]
    )
    sources = [_source(212), _source(7, "sew-schmierstoffe"), _source(209)]
    answer = _answer(True, ("Wert A", [1, 2]), ("Hinweis B", [3]))

    score = _score_answer(question, answer, sources)

    assert score == Score(required=2, retrieved=1, used=1, cited_total=3)


def test_score_answer_counts_a_page_cited_twice_once() -> None:
    answer = _answer(True, ("Wert A", [1]), ("Wert B", [1]))

    score = _score_answer(_question(), answer, [_source(1)])

    assert (score.used, score.cited_total) == (1, 1)


def test_score_answer_tells_a_retrieved_page_from_a_used_one() -> None:
    """The required page is in the prompt, the answer cites another: a loss of generation."""
    answer = _answer(True, ("Wert A", [2]))

    score = _score_answer(_question(), answer, [_source(1), _source(2)])

    assert (score.retrieved, score.used) == (1, 0)


def test_score_rejects_more_used_than_retrieved_pages() -> None:
    with pytest.raises(ValidationError, match="used 2 exceeds retrieved 1"):
        Score(required=2, retrieved=1, used=2, cited_total=2)


def test_score_rejects_more_retrieved_than_required_pages() -> None:
    with pytest.raises(ValidationError, match="retrieved 2 exceeds required 1"):
        Score(required=1, retrieved=2, used=0, cited_total=0)


def _result(question: EvalQuestion, answered: bool, score: Score) -> GenerationResult:
    ids = [1] if answered else []
    return GenerationResult(
        answered=answered,
        statements=_answer(answered, ("Aussage", ids)).statements,
        category=question.category,
        id=question.id,
        answered_by="answering-model",
        input_tokens=100,
        output_tokens=20,
        generation_seconds=1.0,
        score=score,
        pages=[PageRef(document_id="sew-getriebe-ba", page=1)],
    )


def _run(results: list[GenerationResult]) -> GenerationRun:
    return GenerationRun(
        run_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        commit="abc1234",
        eval_set_version="v-test",
        strategy="naive",
        k=5,
        embedding_model="test-embedding-model",
        embedding_dimensions=4,
        generator="test-generator",
        results=results,
    )


def test_log_summary_names_an_unanswerable_question_that_got_an_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    refused = _result(
        _unanswerable(id="q-a"), False, Score(required=0, retrieved=0, used=0, cited_total=0)
    )
    answered = _result(
        _unanswerable(id="q-b"), True, Score(required=0, retrieved=0, used=0, cited_total=1)
    )

    with caplog.at_level(logging.INFO):
        _log_summary(_run([refused, answered]))

    assert was_logged(caplog, logging.INFO, "correct refusals  50.0% (1/2)"), caplog.text
    assert was_logged(caplog, logging.WARNING, "answered although unanswerable: q-b"), caplog.text


def test_log_summary_sets_used_pages_against_retrieved_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A page retrieval never delivered must not count against generation."""
    result = _result(_question(), True, Score(required=2, retrieved=1, used=1, cited_total=1))

    with caplog.at_level(logging.INFO):
        _log_summary(_run([result]))

    assert was_logged(caplog, logging.INFO, "used 100.0% (1/1) of retrieved pages"), caplog.text
    assert was_logged(caplog, logging.INFO, "retrieved  50.0% (1/2) of required"), caplog.text


def _patch_run_generation(
    monkeypatch: pytest.MonkeyPatch,
    questions: list[EvalQuestion],
    selection: PageSelection,
    generated: Generated,
) -> tuple[Mock, Mock]:
    """Replaces everything `run_generation()` reaches outside itself; returns both stage mocks.

    `select_pages` and `generate` are patched where `run_generation()` looks them
    up, in `eval_generate`: the pipeline has tests of its own, this pins what the
    run does with what the stages hand back.
    """
    eval_set = EvalSet(version="v-test", questions=questions)
    monkeypatch.setattr(eval_generate, "load_eval", Mock(return_value=eval_set))
    monkeypatch.setattr(eval_generate, "get_openai_client", Mock())
    monkeypatch.setattr(eval_generate, "get_anthropic_client", Mock())
    monkeypatch.setattr(eval_generate, "get_connection", MagicMock())
    select = Mock(return_value=selection)
    generate = Mock(return_value=generated)
    monkeypatch.setattr(eval_generate, "select_pages", select)
    monkeypatch.setattr(eval_generate, "generate", generate)
    return select, generate


def _selection(pages: list[Source], *, reranked: bool) -> PageSelection:
    return PageSelection(
        candidates=pages,
        pages=pages,
        retrieval_seconds=0.1,
        rerank_seconds=0.5 if reranked else None,
        rerank_input_tokens=1200 if reranked else 0,
        rerank_output_tokens=80 if reranked else 0,
    )


def _generated(answer: GeneratedAnswer) -> Generated:
    return Generated(answer=answer, model="answering-model", input_tokens=6000, output_tokens=200)


def test_run_generation_records_the_answer_its_pages_and_its_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = [_source(9), _source(1)]
    _patch_run_generation(
        monkeypatch,
        [_question()],
        _selection(pages, reranked=True),
        _generated(_answer(True, ("Wert A", [2]))),
    )

    run = run_generation(
        k=2,
        candidates=20,
        reranker="test-reranker",
        generator="test-generator",
        runs_path=tmp_path / "runs.jsonl",
    )

    result = run.results[0]
    assert result.answered
    assert result.pages == [
        PageRef(document_id="sew-getriebe-ba", page=9),
        PageRef(document_id="sew-getriebe-ba", page=1),
    ]
    assert result.score == Score(required=1, retrieved=1, used=1, cited_total=1)
    assert (result.input_tokens, result.output_tokens) == (6000, 200)
    assert (run.generator, run.reranker, run.candidates) == ("test-generator", "test-reranker", 20)
    assert (run.rerank_input_tokens, run.rerank_output_tokens) == (1200, 80)


def test_run_generation_passes_the_question_text_not_the_eval_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The eval question carries its expected pages; in a prompt they let the model copy."""
    select, generate = _patch_run_generation(
        monkeypatch,
        [_question(question="Wie oft Lager prüfen?")],
        _selection([_source(1)], reranked=False),
        _generated(_answer(True, ("Wert A", [1]))),
    )

    run_generation(generator="test-generator", runs_path=tmp_path / "runs.jsonl")

    assert select.call_args.args[2] == "Wie oft Lager prüfen?"
    assert generate.call_args.kwargs["question"] == "Wie oft Lager prüfen?"
    assert generate.call_args.kwargs["model"] == "test-generator"


def test_run_generation_records_no_rerank_tokens_without_a_reranker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """None, not 0: never measured is not the same as measured at zero."""
    _patch_run_generation(
        monkeypatch,
        [_question()],
        _selection([_source(1)], reranked=False),
        _generated(_answer(True, ("Wert A", [1]))),
    )

    run = run_generation(generator="test-generator", runs_path=tmp_path / "runs.jsonl")

    assert (run.rerank_input_tokens, run.rerank_output_tokens) == (None, None)


def test_run_generation_appends_the_run_to_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_generation(
        monkeypatch,
        [_question()],
        _selection([_source(1)], reranked=False),
        _generated(_answer(True, ("Wert A", [1]))),
    )
    runs_path = tmp_path / "generation" / "runs.jsonl"

    run = run_generation(generator="test-generator", runs_path=runs_path)

    assert GenerationRun.model_validate_json(runs_path.read_text(encoding="utf-8")) == run


def test_run_generation_rejects_candidates_without_a_reranker(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="candidates and reranker go together"):
        run_generation(candidates=20, generator="test-generator", runs_path=tmp_path / "r.jsonl")
