"""The way from a question to the answer the API returns: pages, answer, sources."""

import logging
from functools import cache

from anthropic import Anthropic
from openai import OpenAI
from psycopg import Connection
from pydantic import BaseModel, ConfigDict

from anlagen_copilot.corpus import CorpusDocument, load_corpus
from anlagen_copilot.generate import Statement
from anlagen_copilot.pipeline import answer_question
from anlagen_copilot.settings import Strategy

logger = logging.getLogger(__name__)

# Long enough to recognise the page on a source card, short enough that five
# cards do not carry five full manual pages in every response.
_EXCERPT_CHARS = 300


class Citation(BaseModel):
    """One page the answer may cite, with the metadata a source card shows.

    `n` is the id the statements cite. It counts from 1 over the pages after
    reranking, as `generate()` numbered them in the prompt; counted any other
    way, statement [2] would point at the wrong card.

    Title, manufacturer, doc type and the link come from `corpus.yaml`, not
    from the table. `url` opens the manufacturer's PDF at this page; `page` is
    the page of the original PDF, so the jump lands right for excerpted
    documents too. `excerpt` stands in for the full page, which would be too
    long for a card and for the response.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int
    document_id: str
    title: str
    manufacturer: str
    doc_type: str
    page: int
    url: str
    score: float
    excerpt: str


class AskResponse(BaseModel):
    """The answer to one question and the pages its statements cite.

    Only what the caller needs for this one question. Timings and tokens go to
    the log, for the developer; the configuration is the same for every
    question and has no place in each answer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    answered: bool
    statements: list[Statement]
    citations: list[Citation]


def answer(
    openai_client: OpenAI,
    anthropic_client: Anthropic,
    question: str,
    conn: Connection,
    strategy: Strategy,
    *,
    k: int,
    per_document: int | None,
    candidates: int | None,
    reranker: str | None,
    rerank_temperature: float,
    generation_model: str,
) -> AskResponse:
    """Answer `question` and attach a source card for every page the answer was given.

    Every page in the prompt becomes a citation, cited or not, and `n` is its
    position there: the statements cite by that position, so the card for
    statement [2] is `citations[1]`. Keeping the uncited pages lets a client
    show what the answer could have drawn on.

    Timings and tokens are logged rather than returned.

    Raises:
        Whatever `answer_question()` raises.
    """
    answered = answer_question(
        openai_client,
        anthropic_client,
        question,
        conn,
        strategy,
        k=k,
        per_document=per_document,
        candidates=candidates,
        reranker=reranker,
        rerank_temperature=rerank_temperature,
        generation_model=generation_model,
    )
    selection, generated = answered.selection, answered.generated

    documents = _documents_by_id()
    citations = [
        Citation(
            n=n,
            document_id=source.document_id,
            title=documents[source.document_id].title,
            manufacturer=documents[source.document_id].manufacturer,
            doc_type=documents[source.document_id].doc_type,
            page=source.page,
            url=f"{documents[source.document_id].url}#page={source.page}",
            score=source.score,
            excerpt=source.content[:_EXCERPT_CHARS],
        )
        for n, source in enumerate(selection.pages, start=1)
    ]

    logger.info(
        "answered=%s, %d pages, retrieval %.1fs, rerank %s, generation %.1fs, "
        "tokens rerank %d/%d, generation %d/%d",
        generated.answer.answered,
        len(selection.pages),
        selection.retrieval_seconds,
        f"{selection.rerank_seconds:.1f}s" if selection.rerank_seconds is not None else "off",
        answered.generation_seconds,
        selection.rerank_input_tokens,
        selection.rerank_output_tokens,
        generated.input_tokens,
        generated.output_tokens,
    )

    return AskResponse(
        answered=generated.answer.answered,
        statements=generated.answer.statements,
        citations=citations,
    )


@cache
def _documents_by_id() -> dict[str, CorpusDocument]:
    """Load the manifest once per process and index its documents by id.

    The manifest does not change while the server runs, and every answer looks
    up the title of each cited page in it.
    """
    return {document.id: document for document in load_corpus().documents}
