"""Generate an answer from the reranked pages.

The last stage of the pipeline. The model may only use the pages it is given
and names, for each statement, the pages the statement comes from.
"""

from typing import Self

from anthropic import Anthropic, transform_schema
from anthropic.types import JSONOutputFormatParam, TextBlock
from pydantic import BaseModel, ConfigDict, model_validator

from anlagen_copilot.retrieval import Source

_SYSTEM_PROMPT = """\
You answer technical questions on drive engineering — gear units, motors,
frequency inverters, lubricants — from pages of the manufacturers' manuals.
The pages and the question are in German. Answer in German.

The person asking is a technician at the machine and acts on your answer.
Answer only from the pages, even where you believe you know better: a value
from general knowledge that differs from the manual can damage the machine.
Copy values, units and type designations exactly as they appear on the page;
do not convert, round or complete them.

Answer as a list of statements. A statement is one sentence, or one working
step, and carries the ids of the pages it comes from in sources.

Sources:
Each page carries an id and a page number. Put ids in sources, never page
numbers. List a page only if the statement is actually on it. A page on the
same topic or with the same vocabulary is not a source. Every statement that
states a fact needs at least one id. Do not write ids, page numbers or
document names into the text; sources carries them.

Whether the pages answer the question:
- They answer it: set answered to true.
- They answer part of it: set answered to true, answer that part, and add a
  statement that names what the pages do not cover. Do not fill the gap
  yourself. That statement has empty sources.
- They do not answer it: set answered to false and say in one or two
  statements what is missing, all with empty sources. Add no other facts,
  not even ones from the pages: a refusal cites no page, so any fact in it
  would stand without a source. If the question
  assumes something the pages never mention, such as a feature the device
  may not have, say that the pages do not mention it instead of answering
  the assumption.

The pages were extracted from PDFs, and tables often lose their columns on the
way. If you cannot tell which value belongs to which row, or two pages
contradict each other, say so and cite both. Do not pick one or guess.

Keep answers short, precise and technical.
"""


def _build_prompt(question: str, sources: list[Source]) -> str:
    """Number each page from 1 and put the question after the pages."""
    pages = "\n\n".join(
        f'<page id="{n}" document="{source.document_id}" page="{source.page}">\n'
        f"{source.content}\n"
        "</page>"
        for n, source in enumerate(sources, start=1)
    )
    return f"{pages}\n\n<question>\n{question}\n</question>"


class Statement(BaseModel):
    """One sentence of the answer and the ids of the pages it comes from."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    text: str
    sources: list[int]


class GeneratedAnswer(BaseModel):
    """The answer as a list of statements. answered is false if the pages lack the answer."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    answered: bool
    statements: list[Statement]

    @model_validator(mode="after")
    def check_sources_match_answered(self) -> Self:
        """Check that a refusal cites no page and an answer cites at least one.

        A refusal that cites a page contradicts itself: either the page answers
        the question or it does not. An answer that cites no page at all is a
        claim from the model's own knowledge, which the prompt forbids.

        Raises:
            ValueError: When either rule is broken. For a refusal the message
                names the first statement that cites a page.
        """
        cited = [statement for statement in self.statements if statement.sources]

        if not self.answered and cited:
            raise ValueError(f"The answer is a refusal but cites sources, in: {cited[0].text!r}")
        if self.answered and not cited:
            raise ValueError("The answer cites no source for any of its statements")
        return self


class Generated(BaseModel):
    """What one call produced: the answer and what it cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: GeneratedAnswer
    input_tokens: int
    output_tokens: int


# Built from the model, so schema and validation cannot drift apart.
_OUTPUT_FORMAT: JSONOutputFormatParam = {
    "type": "json_schema",
    "schema": transform_schema(GeneratedAnswer),
}


def _check_ids(answer: GeneratedAnswer, source_count: int) -> None:
    """Check that every cited id points to one of the given pages.

    The schema cannot do this: structured outputs do not allow `minimum` or
    `maximum`, and the schema does not know how many pages were in the prompt.
    Without the check, an id of 0 would quietly select the last page, because
    `sources[0 - 1]` is `sources[-1]`.

    Raises:
        ValueError: On the first id outside 1 to `source_count`. The message
            names the id and the statement, so a failed eval run shows what the
            model claimed.
    """
    for statement in answer.statements:
        for source_id in statement.sources:
            if not 1 <= source_id <= source_count:
                raise ValueError(
                    f"The answer cites source {source_id}, but only sources 1 to "
                    f"{source_count} were given, in: {statement.text!r}"
                )


def generate(client: Anthropic, question: str, sources: list[Source], *, model: str) -> Generated:
    """Answer a question from the given pages and return the answer with the tokens spent.

    The ids in the answer count from 1 in the order of `sources`, as
    `_build_prompt()` numbers them. They are checked here but not turned into
    pages: whoever needs the page looks it up in the same `sources` list.

    An empty `sources` list fails instead of becoming a refusal. The search
    always returns pages as long as the table holds rows, so an empty list means
    a misconfigured run, such as a strategy without rows. Recorded as a refusal,
    it would look like a correct answer.

    The call uses `messages.create()` and validates the text here, not
    `messages.parse()`. `parse()` validates before the stop reason can be
    checked, so an answer cut off by `max_tokens` would surface as a JSON error
    instead of naming the stop reason.

    Raises:
        ValueError: When `sources` is empty, the model stops early (`max_tokens`,
            `refusal`) or returns no text, the answer breaks its schema or its
            rules (a `pydantic.ValidationError`, which is a `ValueError`), or it
            cites an id outside `sources`. A cut-off answer is never passed on
            as a complete one.
    """
    if not sources:
        raise ValueError(f"No sources given for this question: {question!r}")

    message = client.messages.create(
        model=model,
        max_tokens=16000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(question, sources)}],
        output_config={"format": _OUTPUT_FORMAT},
    )

    if message.stop_reason != "end_turn":
        raise ValueError(
            f"{model} did not finish generating the answer (stop reason: {message.stop_reason})"
        )

    block = next((b for b in message.content if isinstance(b, TextBlock)), None)
    if block is None:
        raise ValueError(f"{model} returned no text to read the answer from")

    answer = GeneratedAnswer.model_validate_json(block.text)
    _check_ids(answer, len(sources))

    return Generated(
        answer=answer,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
