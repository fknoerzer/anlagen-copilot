"""Similarity search over the indexed chunks.

The read side of the pipeline: a question goes in, the pages nearest to it come
back. Purely reading — nothing here writes, so a query can be repeated as often
as an eval run needs.
"""

from openai import OpenAI
from pgvector import Vector
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel, ConfigDict

from anlagen_copilot.embeddings import embed
from anlagen_copilot.settings import Strategy

_SQL_TOP_K = """
            SELECT document_id, page, content,
                   1 - (embedding <=> %(vec)s) AS score
            FROM chunks
            WHERE strategy = %(strategy)s
            ORDER BY embedding <=> %(vec)s
            LIMIT %(k)s
            """

_SQL_PER_DOCUMENT = """
            SELECT document_id, page, content, score FROM (
                SELECT document_id, page, content,
                       1 - (embedding <=> %(vec)s) AS score,
                       ROW_NUMBER() OVER (PARTITION BY document_id
                                          ORDER BY embedding <=> %(vec)s) AS rank
                FROM chunks
                WHERE strategy = %(strategy)s
            ) candidates
            WHERE rank <= %(m)s
            ORDER BY score DESC
            LIMIT %(k)s
            """


class Source(BaseModel):
    """One retrieved page, as far as the database knows it.

    Only `document_id`, `page`, `content` and `score` are filled here. Title,
    manufacturer, doc type and the PDF link live in `corpus.yaml`, not in the
    table, and `excerpt` is cut from `content` later — the answering layer adds
    all five, which is why they are optional rather than required.

    `extra="forbid"` earns its place on the way in: `class_row(Source)` hands
    every selected column to the constructor by name, so a column the model
    does not know is a mismatch between query and model — better refused here
    than dropped and missed. `frozen=True` means the answering layer builds a
    new object with `model_copy(update=...)` rather than filling the fields in
    place, which is how the rest of the models in this project behave too.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    title: str | None = None
    manufacturer: str | None = None
    doc_type: str | None = None
    page: int
    score: float
    excerpt: str | None = None
    pdf_url: str | None = None
    content: str


def retrieve_global(
    client: OpenAI, text: str, conn: Connection, strategy: Strategy, *, k: int = 5
) -> list[Source]:
    """Return the `k` chunks closest to `text`, best match first.

    `score` is a similarity, not a distance: 1.0 is identical, and higher is
    better. `<=>` is the only operator that may be used here — the HNSW index is
    built with `vector_cosine_ops`, and `<->` or `<#>` would quietly fall back to
    a sequential scan over a different metric.

    The query vector is wrapped in `Vector()` because `register_vector()`
    registers a dumper for `Vector` and `numpy.ndarray`, not for `list`. Beside
    an operator that is not a cosmetic difference: a bare list fails with
    `operator does not exist: vector <=> double precision[]`.

    `strategy` has no default on purpose. Comparing the strategies is what the
    eval set exists for, and a value read from the settings would make the
    result depend on the environment instead of on the call.

    Raises:
        ValueError: When `k` is below 1. `LIMIT 0` would return no rows at all,
            which is indistinguishable from finding nothing.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1 (chunks to retrieve), got {k}")

    embedding = embed(client, text)
    params: dict[str, object] = {"vec": Vector(embedding), "strategy": strategy, "k": k}

    with conn.cursor(row_factory=class_row(Source)) as cur:
        return cur.execute(_SQL_TOP_K, params).fetchall()


def retrieve_per_document(
    client: OpenAI,
    text: str,
    conn: Connection,
    strategy: Strategy,
    *,
    k: int = 5,
    per_document: int,
) -> list[Source]:
    """Return the `k` best chunks, at most `per_document` of them from one document.

    What `retrieve_global()` cannot do: a multi-hop question needs a source from a
    second manual, but the pages of one manual resemble each other and fill the
    top k on their own. The cap reserves room for the other documents.

    Ranking every row is what the window function costs: this query cannot use the
    HNSW index and scores exactly rather than approximately, which is why
    `retrieve_global()` stays the path the recorded runs were measured on.

    `rank` exists only to filter on and never leaves the subquery — `Source`
    forbids unknown fields, and `class_row` hands it every selected column.

    Raises:
        ValueError: When `k` or `per_document` is below 1. Either would return no
            rows at all, which is indistinguishable from finding nothing.
    """
    if per_document < 1:
        raise ValueError(
            f"per_document must be at least 1 (chunks per document), got {per_document}"
        )

    if k < 1:
        raise ValueError(f"k must be at least 1 (chunks to retrieve), got {k}")

    embedding = embed(client, text)
    params: dict[str, object] = {
        "vec": Vector(embedding),
        "strategy": strategy,
        "k": k,
        "m": per_document,
    }

    with conn.cursor(row_factory=class_row(Source)) as cur:
        return cur.execute(_SQL_PER_DOCUMENT, params).fetchall()
