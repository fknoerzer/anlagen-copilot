from unittest.mock import MagicMock

import psycopg
import pytest
from helpers import NO_CLIENT, fake_embed
from openai import OpenAI
from pgvector import Vector

from anlagen_copilot import retrieval
from anlagen_copilot.db import get_connection
from anlagen_copilot.retrieval import Source, retrieve
from anlagen_copilot.settings import Strategy, get_settings


def test_retrieve_rejects_k_below_one() -> None:
    """`LIMIT 0` would return no rows, which reads exactly like finding nothing.

    That is what the guard is for, and why `k=0` rather than a negative value:
    0 is the boundary a caller reaches by accident, -1 is not.
    """
    conn = MagicMock()

    with pytest.raises(ValueError):
        retrieve(NO_CLIENT, "Wo liegt das Distanzrohr?", conn, "naive", k=0)


def test_retrieve_sends_a_cosine_query_with_the_given_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checks the statement that goes out, not the rows the fake hands back.

    The SQL fragments are load-bearing rather than cosmetic. `<=>` has to
    appear twice — once in the score, once in the ORDER BY — because changing
    only one of them leaves the substring intact while the score turns into a
    distance. And a parameter arriving in `params` says nothing about the query
    using it, hence `LIMIT %(k)s` and `WHERE strategy = %(strategy)s`.
    """
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.return_value.fetchall.return_value = [
        Source(document_id="sew-getriebe-ba", page=12, score=0.87, content="Distanzrohr [17]")
    ]
    monkeypatch.setattr(retrieval, "embed", fake_embed)

    k = 3
    strategy: Strategy = "naive"

    sources = retrieve(NO_CLIENT, "Wo liegt das Distanzrohr?", conn, strategy, k=k)

    sql, params = cursor.execute.call_args.args
    assert len(sources) == 1
    assert isinstance(params["vec"], Vector)
    assert sql.count("<=>") == 2
    assert "LIMIT %(k)s" in sql
    assert "WHERE strategy = %(strategy)s" in sql
    assert "<->" not in sql and "<#>" not in sql
    assert (params["strategy"], params["k"]) == (strategy, k)
    assert conn.cursor.call_args.kwargs["row_factory"] is not None


@pytest.mark.integration
def test_retrieve_maps_the_selected_columns_onto_source(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one thing a mock cannot reach: `class_row` against real column names.

    Everywhere else the `Source` objects are put into the fake cursor by the
    test itself, so the SELECT list could name anything. Here they are built by
    psycopg from the columns the query actually returns.

    The vector width comes from the settings rather than from `fake_embed`:
    the column is `VECTOR(embedding_dimensions)` and a four-value vector would
    be rejected by the INSERT, not by the mapping under test.

    Runs against `"advanced"` and clears that strategy first, both inside the
    transaction that is rolled back: a developer database holds the real
    ingested chunks, and `retrieve()` searches the whole table. Filtering by an
    unused strategy is what makes the result depend on this test's rows only —
    and it exercises the `WHERE strategy` clause against real data on the way.
    """
    vector = [0.1] * get_settings().embedding_dimensions

    def embed_fixed(client: OpenAI, text: str) -> list[float]:
        return vector

    monkeypatch.setattr(retrieval, "embed", embed_fixed)

    # `Rollback` leaves the table as it was found — no cleanup step that could
    # itself fail, and no row leaking into the next test.
    with get_connection() as conn, conn.transaction() as tx:
        conn.execute("DELETE FROM chunks WHERE strategy = 'advanced'")
        conn.execute(
            """
            INSERT INTO chunks (strategy, document_id, page, content, embedding)
            VALUES (%s, %s, %s, %s, %s)
            """,
            ("advanced", "roundtrip-doc", 12, "Distanzrohr [17]", Vector(vector)),
        )
        sources = retrieve(NO_CLIENT, "egal", conn, "advanced", k=1)
        raise psycopg.Rollback(tx)

    assert len(sources) == 1
    source = sources[0]
    assert (source.document_id, source.page, source.content) == (
        "roundtrip-doc",
        12,
        "Distanzrohr [17]",
    )
    # An identical vector has cosine distance 0, so the score is a similarity
    # of 1.0 — which is what tells `1 - (… <=> …)` apart from a bare distance.
    assert source.score == pytest.approx(1.0)


@pytest.mark.integration
def test_retrieve_returns_the_best_match_first(
    db_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ORDER BY, checked where it is visible: two rows, the closer one first.

    The rows go in the other way round on purpose. Without the ORDER BY a scan
    over two rows hands them back in insertion order, so the wrong one would
    come first and the test says so.

    `far` is orthogonal to the query vector — cosine similarity 0 against 1 for
    the identical one — which keeps the expected order independent of floating
    point.

    Runs against `"advanced"` and clears that strategy first, both inside the
    transaction that is rolled back: a developer database holds the real
    ingested chunks, and `retrieve()` searches the whole table. Filtering by an
    unused strategy is what makes the result depend on this test's rows only —
    and it exercises the `WHERE strategy` clause against real data on the way.
    """
    dimensions = get_settings().embedding_dimensions
    near = [0.1] * dimensions
    far = [0.1] * (dimensions // 2) + [-0.1] * (dimensions - dimensions // 2)

    def embed_fixed(client: OpenAI, text: str) -> list[float]:
        return near

    monkeypatch.setattr(retrieval, "embed", embed_fixed)

    with get_connection() as conn, conn.transaction() as tx:
        conn.execute("DELETE FROM chunks WHERE strategy = 'advanced'")
        for page, vector in ((1, far), (2, near)):
            conn.execute(
                """
                INSERT INTO chunks (strategy, document_id, page, content, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("advanced", "order-doc", page, f"Seite {page}", Vector(vector)),
            )
        sources = retrieve(NO_CLIENT, "egal", conn, "advanced", k=2)
        raise psycopg.Rollback(tx)

    assert [source.page for source in sources] == [2, 1]
    assert sources[0].score > sources[1].score
