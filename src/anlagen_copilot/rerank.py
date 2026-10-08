"""Reordering retrieved pages by how well a model judges them to answer a question.

The second stage after the vector search: the search decides what is a
candidate, the model reads question and page together and decides what answers.
"""

import logging
from typing import Literal

from anthropic import Anthropic, transform_schema
from anthropic.types import JSONOutputFormatParam, TextBlock
from pydantic import BaseModel, ConfigDict

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


# The id is repeated back instead of implied by the position: without it the
# model graded nearly every page 0 (ADR 004). Kept out of the docstring, which
# goes into the schema the model reads.
class Grade(BaseModel):
    """The grade of one page; id is the number the page carries in the prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: int
    grade: Relevance


class _Grades(BaseModel):
    """How well each numbered page answers the question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grades: list[Grade]


# Built from the model, so schema and validation cannot drift apart.
_OUTPUT_FORMAT: JSONOutputFormatParam = {
    "type": "json_schema",
    "schema": transform_schema(_Grades),
}


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
    # The model that answered, from the response: an alias may point to a newer
    # snapshot. None when no call was made.
    model: str | None = None
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

    The grades come back as structured output: the API holds the text to the
    schema of `_Grades`, so a malformed list cannot arise. The text is validated
    here rather than through `messages.parse()`, because `parse()` validates
    before the stop reason can be checked. An answer that does not fit the
    schema still ends the run: falling back to the vector order would record a
    measurement that looks like reranking and is not.

    Raises:
        ValueError: When `top_n` is below 1, when the model stopped for any
            reason other than finishing, or when the response holds no text.
        pydantic.ValidationError: When the grades do not match `Grade`.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be at least 1 (pages to keep), got {top_n}")
    if not candidates:
        return Reranked(graded=[], input_tokens=0, output_tokens=0)

    message = client.messages.create(
        model=model,
        # 20 grades take about 250 output tokens (`b03d87b`). Only tokens written
        # are billed, so the headroom costs nothing.
        max_tokens=128 + 64 * len(candidates),
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(question, candidates)}],
        output_config={"format": _OUTPUT_FORMAT},
    )

    if message.stop_reason != "end_turn":
        raise ValueError(f"{model} did not finish its grades (stop reason: {message.stop_reason})")

    block = next((b for b in message.content if isinstance(b, TextBlock)), None)
    if block is None:
        raise ValueError(f"{model} returned no grades (stop reason: {message.stop_reason})")

    grades = _Grades.model_validate_json(block.text).grades
    return Reranked(
        graded=_order(candidates, grades, top_n=top_n),
        model=message.model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
