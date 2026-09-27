import json
from typing import cast

import pytest
from anthropic import Anthropic
from anthropic.types import TextBlock, ThinkingBlock, ToolUseBlock
from helpers import FakeAnthropic, make_message
from pydantic import ValidationError

from anlagen_copilot.generate import (
    _OUTPUT_FORMAT,
    GeneratedAnswer,
    Statement,
    _check_ids,
    generate,
)
from anlagen_copilot.retrieval import Source

# `helpers.NO_CLIENT` is typed as OpenAI.
NO_CLIENT = cast(Anthropic, None)


def _answer_json(answered: bool, *statements: tuple[str, list[int]]) -> str:
    return json.dumps(
        {
            "answered": answered,
            "statements": [{"text": text, "sources": ids} for text, ids in statements],
        }
    )


def _answer(answered: bool, *statements: tuple[str, list[int]]) -> GeneratedAnswer:
    return GeneratedAnswer.model_validate_json(_answer_json(answered, *statements))


def _sources() -> list[Source]:
    return [
        Source(document_id="sew-motoren-drn", page=131, score=0.9, content="Seite 131"),
        Source(document_id="sew-motoren-drn", page=132, score=0.8, content="Seite 132"),
        Source(document_id="sew-getriebe-ba", page=70, score=0.7, content="Seite 70"),
    ]


def _generate(client: FakeAnthropic, sources: list[Source] | None = None) -> None:
    generate(
        cast(Anthropic, client),
        "Frage?",
        _sources() if sources is None else sources,
        model="claude-test",
    )


def test_check_ids_rejects_an_id_above_the_source_count() -> None:
    answer = _answer(True, ("Wert A", [4]))

    with pytest.raises(ValueError, match="cites source 4, but only sources 1 to 3"):
        _check_ids(answer, 3)


def test_check_ids_accepts_the_last_source() -> None:
    """Catches `<` where `<=` belongs: 3 of 3 is valid."""
    _check_ids(_answer(True, ("Wert A", [3])), 3)


def test_check_ids_rejects_zero() -> None:
    """Unchecked, id 0 would select the last page through `sources[-1]`."""
    answer = _answer(True, ("Wert A", [0]))

    with pytest.raises(ValueError, match="cites source 0"):
        _check_ids(answer, 3)


def test_refusal_without_sources_is_valid() -> None:
    answer = _answer(False, ("Die Seiten erwähnen keinen Akku.", []))

    assert not answer.answered


def test_refusal_that_cites_a_page_is_rejected() -> None:
    with pytest.raises(ValidationError, match="refusal but cites sources, in: 'Wert A'"):
        _answer(False, ("Wert A", [1]))


def test_answer_without_any_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cites no source"):
        _answer(True, ("Wert A", []))


def test_partial_answer_names_its_gap_without_a_source() -> None:
    answer = _answer(True, ("Wert A", [1]), ("Zu B enthalten die Seiten nichts.", []))

    assert answer.statements[1] == Statement(text="Zu B enthalten die Seiten nichts.", sources=[])


def test_generate_without_sources_fails_before_the_call() -> None:
    """An empty list means a misconfigured run, not an unanswerable question."""
    with pytest.raises(ValueError, match="No sources given"):
        generate(NO_CLIENT, "Frage?", [], model="claude-test")


def test_generate_returns_the_answer_and_its_tokens() -> None:
    client = FakeAnthropic(make_message(_answer_json(True, ("Wert A", [2]))))

    result = generate(cast(Anthropic, client), "Frage?", _sources(), model="claude-test")

    assert result.answer == _answer(True, ("Wert A", [2]))
    assert (result.input_tokens, result.output_tokens) == (100, 20)


def test_generate_sends_the_schema_and_pages_numbered_from_one() -> None:
    client = FakeAnthropic(make_message(_answer_json(True, ("Wert A", [1]))))

    _generate(client)

    kwargs = client.messages.kwargs
    prompt = kwargs["messages"][0]["content"]  # type: ignore[index]
    assert kwargs["model"] == "claude-test"
    assert kwargs["output_config"] == {"format": _OUTPUT_FORMAT}
    assert '<page id="1" document="sew-motoren-drn" page="131">' in prompt
    assert '<page id="3" document="sew-getriebe-ba" page="70">' in prompt
    assert 'id="0"' not in prompt
    assert prompt.index("</page>") < prompt.index("<question>")


def test_generate_reads_the_text_after_a_thinking_block() -> None:
    """Adaptive thinking puts its block first; the answer is the first text block."""
    message = make_message(
        [
            ThinkingBlock(type="thinking", thinking="", signature="sig"),
            TextBlock(type="text", text=_answer_json(True, ("Wert A", [1]))),
        ]
    )
    client = FakeAnthropic(message)

    result = generate(cast(Anthropic, client), "Frage?", _sources(), model="claude-test")

    assert result.answer.statements[0].sources == [1]


def test_generate_rejects_an_answer_cut_off_by_max_tokens() -> None:
    """ADR 005: the stop reason is checked before the JSON, so the message names it."""
    client = FakeAnthropic(make_message('{"answered": true, "statem', stop_reason="max_tokens"))

    with pytest.raises(ValueError, match="stop reason: max_tokens"):
        _generate(client)


def test_generate_rejects_a_refusal_stop() -> None:
    client = FakeAnthropic(make_message("", stop_reason="refusal"))

    with pytest.raises(ValueError, match="stop reason: refusal"):
        _generate(client)


def test_generate_rejects_a_response_without_text() -> None:
    message = make_message([ToolUseBlock(id="toolu_test", name="x", type="tool_use", input={})])
    client = FakeAnthropic(message)

    with pytest.raises(ValueError, match="no text"):
        _generate(client)


def test_generate_rejects_an_id_outside_the_sources() -> None:
    client = FakeAnthropic(make_message(_answer_json(True, ("Wert A", [4]))))

    with pytest.raises(ValueError, match="cites source 4, but only sources 1 to 3"):
        _generate(client)
