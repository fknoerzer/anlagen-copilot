from typing import cast

import pytest
from anthropic import Anthropic
from anthropic.types import Message, StopReason, TextBlock, ToolUseBlock, Usage
from helpers import was_logged

from anlagen_copilot.rerank import GradedSource, rerank
from anlagen_copilot.retrieval import Source

# `helpers.NO_CLIENT` is typed as OpenAI.
NO_CLIENT = cast(Anthropic, None)


class _FakeMessages:
    """Returns a prepared answer and keeps the request's kwargs."""

    def __init__(self, message: Message) -> None:
        self._message = message
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> Message:
        self.kwargs = kwargs
        return self._message


class _FakeClient:
    """A class, not a MagicMock, so a misspelt attribute raises."""

    def __init__(self, message: Message) -> None:
        self.messages = _FakeMessages(message)


def _message(grades: object, *, stop_reason: StopReason = "tool_use") -> Message:
    """Real SDK types: `rerank()` finds the block with `isinstance`."""
    return Message(
        id="msg_test",
        model="claude-test",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        content=[
            ToolUseBlock(
                id="toolu_test", name="record_grades", type="tool_use", input={"grades": grades}
            )
        ],
        usage=Usage(input_tokens=100, output_tokens=20),
    )


def _candidates() -> list[Source]:
    """Distinct scores, so the tie-break within a grade shows."""
    return [
        Source(document_id="sew-getriebe-ba", page=10, score=0.90, content="Seite zehn"),
        Source(document_id="sew-getriebe-ba", page=11, score=0.80, content="Seite elf"),
        Source(document_id="sew-getriebe-ba", page=12, score=0.70, content="Seite zwölf"),
    ]


def _pages(graded: list[GradedSource]) -> list[int]:
    return [g.source.page for g in graded]


def test_rerank_rejects_top_n_below_one() -> None:
    with pytest.raises(ValueError):
        rerank(NO_CLIENT, "Frage?", _candidates(), model="m", top_n=0)


def test_rerank_without_candidates_makes_no_call() -> None:
    result = rerank(NO_CLIENT, "Frage?", [], model="m", top_n=5)

    assert result.graded == []
    assert (result.input_tokens, result.output_tokens) == (0, 0)


def test_rerank_orders_by_grade_then_by_vector_score() -> None:
    client = _FakeClient(
        _message([{"id": 1, "grade": 1}, {"id": 2, "grade": 1}, {"id": 3, "grade": 3}])
    )

    result = rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=3)

    assert _pages(result.graded) == [12, 10, 11]
    assert [g.grade for g in result.graded] == [3, 1, 1]
    assert (result.input_tokens, result.output_tokens) == (100, 20)


def test_rerank_keeps_only_top_n() -> None:
    client = _FakeClient(
        _message([{"id": 1, "grade": 0}, {"id": 2, "grade": 3}, {"id": 3, "grade": 2}])
    )

    result = rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=2)

    assert _pages(result.graded) == [11, 12]


def test_rerank_numbers_the_pages_from_one_and_forces_the_tool() -> None:
    """An off-by-one still yields a valid result; only the request shows it."""
    client = _FakeClient(
        _message([{"id": 1, "grade": 3}, {"id": 2, "grade": 0}, {"id": 3, "grade": 0}])
    )

    rerank(cast(Anthropic, client), "Wo liegt das Distanzrohr?", _candidates(), model="m", top_n=3)

    kwargs = client.messages.kwargs
    prompt = kwargs["messages"][0]["content"]  # type: ignore[index]
    assert '<page id="1" document="sew-getriebe-ba" page="10">' in prompt
    assert '<page id="3" document="sew-getriebe-ba" page="12">' in prompt
    assert 'id="0"' not in prompt
    assert prompt.index("</page>") < prompt.index("<question>")
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_grades"}
    assert kwargs["max_tokens"] == 128 + 64 * 3


def test_rerank_gives_an_ungraded_page_zero_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Id 99 matches no page and is ignored."""
    client = _FakeClient(_message([{"id": 3, "grade": 2}, {"id": 99, "grade": 3}]))

    with caplog.at_level("WARNING"):
        result = rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=3)

    assert _pages(result.graded) == [12, 10, 11]
    assert [g.grade for g in result.graded] == [2, 0, 0]
    assert was_logged(caplog, 30, "graded 2 of 3"), caplog.text


def test_rerank_repairs_a_grade_list_written_as_text() -> None:
    client = _FakeClient(
        _message('[{"id": 1, "grade": 0}, {"id": 2, "grade": 3}, {"id": 3, "grade": 0},')
    )

    result = rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=1)

    assert _pages(result.graded) == [11]


def test_rerank_rejects_an_answer_cut_off_by_max_tokens() -> None:
    client = _FakeClient(_message([{"id": 1, "grade": 3}], stop_reason="max_tokens"))

    with pytest.raises(ValueError, match="max_tokens"):
        rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=3)


def test_rerank_rejects_a_response_without_tool_call() -> None:
    message = _message([])
    message.content = [TextBlock(type="text", text="Ich bewerte lieber in Prosa.", citations=None)]
    client = _FakeClient(message)

    with pytest.raises(ValueError, match="no grades"):
        rerank(cast(Anthropic, client), "Frage?", _candidates(), model="m", top_n=3)
