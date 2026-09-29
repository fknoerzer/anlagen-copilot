"""The way from a question to the pages a model answers from: search, then rerank.

Shared by both evaluations and, later, the answer endpoint. It knows only the
text of a question, never an eval question: the pipeline answers real questions,
and those come without expected pages.
"""

import time

from anthropic import Anthropic
from openai import OpenAI
from psycopg import Connection
from pydantic import BaseModel, ConfigDict

from anlagen_copilot.rerank import rerank
from anlagen_copilot.retrieval import Source, retrieve_global, retrieve_per_document
from anlagen_copilot.settings import Strategy


class Retrieved(BaseModel):
    """The pages one question produced, before and after reranking, and what that cost.

    Both lists are kept: the retrieval evaluation ranks the expected pages in
    each, the generation only needs `pages`. Without a reranker the two are the
    same list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: list[Source]
    pages: list[Source]
    retrieval_seconds: float
    rerank_seconds: float | None
    rerank_input_tokens: int
    rerank_output_tokens: int


def retrieve_pages(
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
) -> Retrieved:
    """Search for the pages that answer `question` and, with a reranker, regrade them.

    Without a reranker the search fetches `k` pages and those are the result.
    With one it fetches `candidates` pages, and the model keeps the best `k`.
    `per_document` switches the search to `retrieve_per_document()`.

    The clients come in as arguments rather than being built here, so a caller
    can pass fakes, and one run builds them once.
    """
    fetch = k if candidates is None else candidates

    retrieval_start = time.perf_counter()
    if per_document is not None:
        found = retrieve_per_document(
            openai_client, question, conn, strategy, k=fetch, per_document=per_document
        )
    else:
        found = retrieve_global(openai_client, question, conn, strategy, k=fetch)
    retrieval_seconds = time.perf_counter() - retrieval_start

    if reranker is None:
        return Retrieved(
            candidates=found,
            pages=found,
            retrieval_seconds=retrieval_seconds,
            rerank_seconds=None,
            rerank_input_tokens=0,
            rerank_output_tokens=0,
        )

    rerank_start = time.perf_counter()
    reranked = rerank(anthropic_client, question, found, model=reranker, top_n=k)
    rerank_seconds = time.perf_counter() - rerank_start

    return Retrieved(
        candidates=found,
        pages=[graded.source for graded in reranked.graded],
        retrieval_seconds=retrieval_seconds,
        rerank_seconds=rerank_seconds,
        rerank_input_tokens=reranked.input_tokens,
        rerank_output_tokens=reranked.output_tokens,
    )
