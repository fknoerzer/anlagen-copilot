"""Reordering retrieved pages by how well a model judges them to answer a question.

The second stage after the vector search: the search decides what is a
candidate, the model reads question and page together and decides what answers.
"""

import json
import logging
from typing import Literal

from anthropic import Anthropic
from anthropic.types import ToolParam, ToolUseBlock
from pydantic import BaseModel, ConfigDict, field_validator

from anlagen_copilot.retrieval import Source

logger = logging.getLogger(__name__)

Relevance = Literal[0, 1, 2, 3]


_SYSTEM_PROMPT = """\
You grade pages from technical manuals on drive engineering — gear units,
motors, frequency inverters, lubricants — by how well they answer a question.
The pages and the question are in German.

Each page carries a number. Give every number exactly one grade:

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
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "grade": {"type": "integer", "enum": [0, 1, 2, 3]},
                    },
                    "additionalProperties": False,
                    "required": ["id", "grade"],
                },
            }
        },
        "required": ["grades"],
    },
}


class Grade(BaseModel):
    """One grade as the model returns it; `id` is the page's number in the prompt.

    The id is repeated back rather than implied by the position. A flat list of
    grades was measured and costs under a third of the output tokens — and, in
    three calls each on the questions run 11 lost (q-007, q-033, q-034), finds
    4 of 12 expected sources where this shape finds 11 (see `1f4d839`).
    Naming the page before grading it is what keeps the model from writing out a
    uniform row of zeroes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: int
    grade: Relevance


class _Grades(BaseModel):
    """The whole tool input, validated in one step — the SDK types it as `object`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grades: list[Grade]

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


def _order(candidates: list[Source], grades: list[Grade], *, top_n: int) -> list[GradedSource]:
    """Sort the candidates by grade, then by vector score, and keep the first `top_n`.

    Numbering starts at 1, as in `_build_prompt()` — a shift of one would hand
    every page its neighbour's grade without anything failing. A page the model
    left out gets 0 and stays in the list; an id matching no page is ignored.

    Grade first, vector score second: within one grade the search order decides,
    so the model only has to say which pages belong in a band, not how they rank
    inside it. A run where every page is graded 0 therefore comes out in plain
    vector order — which is what a flat grade list produced, and how run 11 was
    recognised as a reranker that had stopped reranking.
    """
    if len(grades) != len(candidates):
        logger.warning("graded %d of %d pages", len(grades), len(candidates))

    by_id = {g.id: g.grade for g in grades}
    graded = []
    for n, source in enumerate(candidates, start=1):
        grade = by_id.get(n)
        graded.append(GradedSource(source=source, grade=grade if grade is not None else 0))
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
            reason other than the tool call, or when the response holds no tool
            call.
        pydantic.ValidationError: When the grades do not match `Grade`, or
            arrive as text that does not parse.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be at least 1 (pages to keep), got {top_n}")
    if not candidates:
        return Reranked(graded=[], input_tokens=0, output_tokens=0)

    message = client.messages.create(
        model=model,
        # Twenty grades were measured at 315 output tokens, which this exceeds
        # fourfold. The limit is a ceiling, not a purchase: only the tokens
        # actually written are billed, so the headroom costs nothing.
        max_tokens=128 + 64 * len(candidates),
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
