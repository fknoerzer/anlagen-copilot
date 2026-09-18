"""Reordering retrieved pages by how well a model judges them to answer a question.

The second stage after the vector search: the search decides what is a
candidate, the model reads question and page together and decides what answers.
"""

import json
from typing import Literal

from anthropic import Anthropic
from anthropic.types import ToolParam, ToolUseBlock
from pydantic import BaseModel, ConfigDict, field_validator

from anlagen_copilot.retrieval import Source

Relevance = Literal[0, 1, 2, 3]


_SYSTEM_PROMPT = """\
You grade pages from technical manuals on drive engineering — gear units,
motors, frequency inverters, lubricants — by how well they answer a question.
The pages and the question are in German.

Return one grade per page, in the order the pages are given: the first grade is
for the first page. Return exactly as many grades as there are pages, and skip
none — the position is what ties a grade to its page.

The scale:

3 — The page answers the question directly: the value, step or relationship
    asked for is on it.
2 — The page supplies part of the answer that is not enough on its own: one of
    several required facts, or the reference to where the answer is found.
1 — The page covers the same topic but contributes nothing to the answer.
0 — The page has nothing to do with the question.

Grade only what is on the page, not what you know yourself. The same component
or the same vocabulary does not make a page helpful: the pages of one manual
resemble each other, and that resemblance is exactly what you have to tell apart
from an actual answer. Values in tables count as much as running text.
"""


_GRADE_TOOL: ToolParam = {
    "name": "record_grades",
    "description": "Record how well each numbered page answers the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grades": {
                "type": "array",
                "description": (
                    "One grade per page, in the order the pages were given: "
                    "the first entry grades page 1."
                ),
                "items": {"type": "integer", "enum": [0, 1, 2, 3]},
            }
        },
        "required": ["grades"],
        "additionalProperties": False,
    },
}


class _Grades(BaseModel):
    """The whole tool input, validated in one step — the SDK types it as `object`.

    A plain list of grades rather than id/grade pairs: the position carries the
    page number, which costs a third of the output tokens and removes the one
    nesting level the model kept getting wrong.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    grades: list[Relevance]

    @field_validator("grades", mode="before")
    @classmethod
    def _parse_text(cls, value: object) -> object:
        """Parse a list the model wrote as text instead of structuring it.

        Seen in three of eight calls on the longest prompt in the corpus, always
        with the closing bracket missing. Repairing that one character beats
        losing a forty-minute run to a formatting slip. A list that breaks off
        mid-entry still fails here, and should: only the bracket is restored,
        nothing is guessed.
        """
        if not isinstance(value, str):
            return value
        text = value.strip().rstrip(",")
        return json.loads(text if text.endswith("]") else text + "]")


class GradedSource(BaseModel):
    """A retrieved page with the grade it received.

    A wrapper rather than a field on `Source`: the grade exists only after
    reranking, and `Source` already carries optionals that the database never
    fills.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Source
    grade: Relevance


class Reranked(BaseModel):
    """What one call produced: the ordered pages and what they cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    graded: list[GradedSource]
    input_tokens: int
    output_tokens: int


def _build_prompt(question: str, candidates: list[Source]) -> str:
    """Number each candidate from 1 and put the question after the pages."""
    pages = "\n\n".join(
        f'<page id="{n}" document="{source.document_id}" page="{source.page}">\n'
        f"{source.content}\n"
        "</page>"
        for n, source in enumerate(candidates, start=1)
    )
    return f"{pages}\n\n<question>\n{question}\n</question>"


def _order(candidates: list[Source], grades: list[Relevance], *, top_n: int) -> list[GradedSource]:
    """Pair each candidate with the grade at its position and keep the best `top_n`.

    Grade first, vector score second: within one grade the search order decides,
    so the model only has to say which pages belong in a band, not how they rank
    inside it.

    A count that does not match ends this: with positions there is no way to tell
    a skipped page from an answer that stopped early, and every grade after the
    gap would belong to the wrong page without anything looking wrong.

    Raises:
        ValueError: When the number of grades differs from the number of pages.
    """
    if len(grades) != len(candidates):
        raise ValueError(f"got {len(grades)} grades for {len(candidates)} pages")

    graded = [
        GradedSource(source=source, grade=grade)
        for source, grade in zip(candidates, grades, strict=True)
    ]
    graded.sort(key=lambda g: (g.grade, g.source.score), reverse=True)
    return graded[:top_n]


def rerank(
    client: Anthropic, question: str, candidates: list[Source], *, model: str, top_n: int
) -> Reranked:
    """Grade every candidate against `question` in one call and return the best `top_n`.

    `question` is the text alone, never an eval question: those carry their
    expected sources, and a prompt holding them would let the model copy the
    answer.

    The tool call is forced, so the grades arrive as structured input rather
    than as text to parse. An answer that does not fit the schema ends the run:
    falling back to the vector order would record a measurement that looks like
    reranking and is not.

    Raises:
        ValueError: When `top_n` is below 1, when the model stopped for any
            reason other than the tool call, when the response holds no tool
            call, or when the grades do not count out against the pages.
        pydantic.ValidationError: When a grade is outside `Relevance`, or the
            grades arrive as text that does not parse.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be at least 1 (pages to keep), got {top_n}")
    if not candidates:
        return Reranked(graded=[], input_tokens=0, output_tokens=0)

    message = client.messages.create(
        model=model,
        # Twenty grades were measured at 92 output tokens, which this exceeds
        # eightfold. The limit is a ceiling, not a purchase: only the tokens
        # actually written are billed, so the headroom costs nothing.
        max_tokens=128 + 32 * len(candidates),
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(question, candidates)}],
        tools=[_GRADE_TOOL],
        tool_choice={"type": "tool", "name": "record_grades"},
    )

    if message.stop_reason != "tool_use":
        raise ValueError(f"{model} did not finish its grades (stop reason: {message.stop_reason})")

    block = next((b for b in message.content if isinstance(b, ToolUseBlock)), None)
    if block is None:
        raise ValueError(f"{model} returned no grades (stop reason: {message.stop_reason})")

    grades = _Grades.model_validate(block.input).grades
    return Reranked(
        graded=_order(candidates, grades, top_n=top_n),
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
