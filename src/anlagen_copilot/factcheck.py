"""Checking stored answers against the required facts of the eval set.

A second model reads question, answer and facts and judges each fact on its
own: whether the answer states it, leaves it out or says something else. Which
page is cited is measured elsewhere; this measures whether the content is right.
"""

from collections import Counter
from typing import Literal

from anthropic import Anthropic, transform_schema
from anthropic.types import JSONOutputFormatParam, TextBlock
from pydantic import BaseModel, ConfigDict

from anlagen_copilot.generate import GeneratedAnswer

_SYSTEM_PROMPT = """\
You check answers to questions on drive engineering — gear units, motors,
frequency inverters, lubricants — against a list of required facts. The
question, the answer and the facts are in German.

The answer consists of numbered statements. The required facts are what a
complete answer must contain. Give every required fact exactly one verdict:
none left out, none added, and repeat the fact word for word in the field
`fact`.

present      — The answer states the fact. Different wording is fine; values,
               units, names and conditions must match.
missing      — The answer says nothing about the fact, or only part of it.
contradicted — The answer says something about the fact that does not match:
               a different value, a different condition, the opposite claim,
               or a different answer in its place, such as another formula
               where the fact names one.

A fact with several parts is present only if every part is in the answer. If
one part is stated with a different value, the fact is contradicted; if a
part is simply absent, it is missing.

First write the reason in one sentence, in German: quote or name the
statement that decides the verdict, or say that none does. Then give the
verdict.

Judge only what the answer says, not what you know yourself. Information
beyond the required facts is neither a fault nor a credit here.
"""


class FactVerdict(BaseModel):
    """The verdict on one required fact, with the reason written before it."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fact: str
    reason: str
    verdict: Literal["present", "missing", "contradicted"]


class _FactVerdicts(BaseModel):
    """One verdict for every required fact, none left out and none added."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fact_verdicts: list[FactVerdict]


_OUTPUT_FORMAT: JSONOutputFormatParam = {
    "type": "json_schema",
    "schema": transform_schema(_FactVerdicts),
}


class FactCheck(BaseModel):
    """What one call produced: the verdicts and what they cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checked: list[FactVerdict]
    model: str
    input_tokens: int
    output_tokens: int


def _build_prompt(question: str, answer: GeneratedAnswer, facts: list[str]) -> str:
    """Put the question, the numbered statements and the required facts into one prompt.

    The statements go in without the ids of the pages they cite: this check reads
    only what the answer says, and the pages behind the ids are not in the prompt
    to look them up.
    """
    statements = "\n".join(
        f'<statement id="{n}">{statement.text}</statement>'
        for n, statement in enumerate(answer.statements, start=1)
    )
    required = "\n".join(f"<fact>{fact}</fact>" for fact in facts)
    return (
        f"<question>\n{question}\n</question>\n\n"
        f"<answer>\n{statements}\n</answer>\n\n"
        f"<required_facts>\n{required}\n</required_facts>"
    )


def _check_verdicts(verdicts: list[FactVerdict], facts: list[str]) -> None:
    """Check that the verdicts judge every required fact exactly once and no other.

    Facts are matched by their exact text, which the prompt asks the model to
    repeat word for word. The reranker gives a page it left out the grade 0 and
    carries on, because the reranker is part of the system under test and 0 can
    only cost it a hit. The checker is the measuring instrument: a missing
    verdict counted as present would make an answer complete that was never
    checked, counted as missing it would blame the answer for the checker's
    slip. No default is honest, so a list that does not match ends the run.

    Raises:
        ValueError: When a fact is judged twice, a verdict names a fact that was
            not asked for, or a required fact has no verdict. The message names
            the fact, so a failed run shows what the model wrote.
    """
    judged = Counter(verdict.fact for verdict in verdicts)

    twice = [fact for fact, count in judged.items() if count > 1]
    if twice:
        raise ValueError(f"The fact check judges {twice[0]!r} more than once")

    unknown = [fact for fact in judged if fact not in facts]
    if unknown:
        raise ValueError(f"The fact check judges a fact that was not asked for: {unknown[0]!r}")

    missing = [fact for fact in facts if fact not in judged]
    if missing:
        raise ValueError(f"The fact check gives no verdict for: {missing[0]!r}")


def all_facts_present(verdicts: list[FactVerdict]) -> bool:
    """Tell whether the answer states every required fact.

    A fact that is missing and one that is contradicted both make the answer
    incomplete; which of the two it was stays in the verdicts. An empty list is
    True, as for `all()`; it cannot come from `check_facts()`, which only judges
    answers and whose facts the eval set never leaves empty for them.
    """
    return all(verdict.verdict == "present" for verdict in verdicts)


def check_facts(
    client: Anthropic,
    question: str,
    answer: GeneratedAnswer,
    facts: list[str],
    *,
    model: str,
) -> FactCheck:
    """Judge in one call whether `answer` states each of the required `facts`.

    Only answers are checked, not refusals: a refusal states no facts by design,
    and judging it would count every fact as missing against an answer that was
    right to decline. Whether a refusal was right is measured elsewhere, against
    the category of the question.

    Raises:
        ValueError: When `answer` is a refusal, when the model stopped for any
            reason other than finishing, when the response holds no text, or
            when the verdicts do not match the facts one to one.
        pydantic.ValidationError: When the verdicts do not match `FactVerdict`.
    """
    if not answer.answered:
        raise ValueError("A refusal has no facts to check; call this only for answers")

    message = client.messages.create(
        model=model,
        # The model thinks before it answers, and thinking counts against this
        # limit; four verdicts alone take about 500 tokens. Only tokens written
        # are billed, so the headroom costs nothing.
        max_tokens=16000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(question, answer, facts)}],
        output_config={"format": _OUTPUT_FORMAT},
    )

    if message.stop_reason != "end_turn":
        raise ValueError(
            f"{model} did not finish checking facts (stop reason: {message.stop_reason})"
        )

    block = next((b for b in message.content if isinstance(b, TextBlock)), None)
    if block is None:
        raise ValueError(f"{model} returned no fact verdicts (stop reason: {message.stop_reason})")

    fact_verdicts = _FactVerdicts.model_validate_json(block.text).fact_verdicts

    _check_verdicts(verdicts=fact_verdicts, facts=facts)

    return FactCheck(
        checked=fact_verdicts,
        model=message.model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
