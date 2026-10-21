import json
from typing import cast

import pytest
from anthropic import Anthropic
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock
from helpers import NO_ANTHROPIC, FakeAnthropic, make_answer, make_message
from pydantic import ValidationError

from anlagen_copilot.factcheck import (
    _OUTPUT_FORMAT,
    _SYSTEM_PROMPT,
    FactCheck,
    FactVerdict,
    _build_prompt,
    _check_verdicts,
    check_facts,
)
from anlagen_copilot.generate import GeneratedAnswer

FACTS = ["Die Umgebung reicht von -15 °C bis +40 °C.", "+80 °C ist die Ölsumpftemperatur."]


def _answer() -> GeneratedAnswer:
    return make_answer(
        True,
        ("Das Getriebe läuft bei -15 °C bis +40 °C.", [1]),
        ("Das Öl verträgt bis +80 °C.", [2]),
    )


def _verdict(fact: str, verdict: str = "present") -> dict[str, str]:
    return {"fact": fact, "reason": "Begründung.", "verdict": verdict}


def _verdicts_json(verdicts: object) -> str:
    return json.dumps({"fact_verdicts": verdicts})


def _message(verdicts: object) -> Message:
    return make_message(_verdicts_json(verdicts))


def _check(client: FakeAnthropic) -> FactCheck:
    return check_facts(cast(Anthropic, client), "Frage?", _answer(), FACTS, model="requested")


def test_check_verdicts_accepts_every_fact_once_in_any_order() -> None:
    verdicts = [
        FactVerdict(fact=FACTS[1], reason="r", verdict="missing"),
        FactVerdict(fact=FACTS[0], reason="r", verdict="present"),
    ]

    _check_verdicts(verdicts, FACTS)


@pytest.mark.parametrize(
    ("verdicts", "message"),
    [
        pytest.param([FACTS[0]], "no verdict for", id="fact-without-verdict"),
        pytest.param([FACTS[0], FACTS[1], "Erfunden."], "not asked for", id="verdict-on-unknown"),
        pytest.param([FACTS[0], FACTS[0], FACTS[1]], "more than once", id="fact-judged-twice"),
        pytest.param(
            [FACTS[0], FACTS[1].replace("+80", "80")], "not asked for", id="fact-reworded"
        ),
    ],
)
def test_check_verdicts_rejects_a_list_that_does_not_match_the_facts(
    verdicts: list[str], message: str
) -> None:
    """A reworded fact counts as unknown: facts are matched by their exact text."""
    judged = [FactVerdict(fact=fact, reason="r", verdict="present") for fact in verdicts]

    with pytest.raises(ValueError, match=message):
        _check_verdicts(judged, FACTS)


def test_build_prompt_numbers_the_statements_and_lists_every_fact() -> None:
    prompt = _build_prompt("Welche Temperatur?", _answer(), FACTS)

    assert '<statement id="1">Das Getriebe läuft bei -15 °C bis +40 °C.</statement>' in prompt
    assert '<statement id="2">Das Öl verträgt bis +80 °C.</statement>' in prompt
    assert all(f"<fact>{fact}</fact>" in prompt for fact in FACTS)
    assert prompt.index("<question>") < prompt.index("<answer>") < prompt.index("<required_facts>")


def test_build_prompt_leaves_out_the_cited_page_ids() -> None:
    """The check reads the content only; the pages behind the ids are not in the prompt."""
    prompt = _build_prompt("Frage?", _answer(), FACTS)

    assert "sources" not in prompt
    assert "[1]" not in prompt


def test_check_facts_returns_the_verdicts_and_the_model_that_answered() -> None:
    """An alias may point to a newer snapshot; the run must name the one that judged."""
    client = FakeAnthropic(_message([_verdict(FACTS[0]), _verdict(FACTS[1], "contradicted")]))

    result = _check(client)

    assert [(v.fact, v.verdict) for v in result.checked] == [
        (FACTS[0], "present"),
        (FACTS[1], "contradicted"),
    ]
    assert result.model == "claude-test"
    assert (result.input_tokens, result.output_tokens) == (100, 20)


def test_check_facts_sends_prompt_schema_and_room_for_thinking() -> None:
    client = FakeAnthropic(_message([_verdict(FACTS[0]), _verdict(FACTS[1])]))

    _check(client)

    kwargs = client.messages.kwargs
    assert kwargs["system"] == _SYSTEM_PROMPT
    assert kwargs["output_config"] == {"format": _OUTPUT_FORMAT}
    assert kwargs["max_tokens"] == 16000
    assert kwargs["messages"][0]["content"] == _build_prompt("Frage?", _answer(), FACTS)  # type: ignore[index]


def test_check_facts_reads_the_text_after_a_thinking_block() -> None:
    """The judge always thinks first; its verdicts are in the text block that follows."""
    text = _verdicts_json([_verdict(FACTS[0]), _verdict(FACTS[1])])
    client = FakeAnthropic(
        make_message(
            [
                ThinkingBlock(type="thinking", thinking="", signature="sig"),
                TextBlock(type="text", text=text),
            ]
        )
    )

    result = _check(client)

    assert len(result.checked) == 2


def test_check_facts_refuses_a_refusal_before_any_call() -> None:
    """NO_ANTHROPIC would fail on use, so the error must come first."""
    refusal = make_answer(False, ("Steht nicht in den Seiten.", []))

    with pytest.raises(ValueError, match="refusal"):
        check_facts(NO_ANTHROPIC, "Frage?", refusal, FACTS, model="m")


def test_check_facts_rejects_an_answer_cut_off_by_max_tokens() -> None:
    """The stop reason is checked before the JSON, so the message names it."""
    client = FakeAnthropic(make_message('{"fact_verdicts": [{"fa', stop_reason="max_tokens"))

    with pytest.raises(ValueError, match="max_tokens"):
        _check(client)


def test_check_facts_rejects_a_response_without_text() -> None:
    message = make_message([ToolUseBlock(id="toolu_test", name="x", type="tool_use", input={})])

    with pytest.raises(ValueError, match="no fact verdicts"):
        _check(FakeAnthropic(message))


def test_check_facts_rejects_verdicts_that_skip_a_fact() -> None:
    """ADR 005: a skipped fact must end the run, not count as present."""
    client = FakeAnthropic(_message([_verdict(FACTS[0])]))

    with pytest.raises(ValueError, match="no verdict for"):
        _check(client)


def test_check_facts_rejects_a_verdict_outside_the_three() -> None:
    client = FakeAnthropic(_message([_verdict(FACTS[0], "partly"), _verdict(FACTS[1])]))

    with pytest.raises(ValidationError, match="verdict"):
        _check(client)
