"""Tests für scripts/init_db.py: Schema-Setup (Extension + chunks-Tabelle)."""

from anlagen_copilot.db import get_connection
from anlagen_copilot.scripts.init_db import init_db

# Kein `db_schema` nötig: beide Tests rufen `init_db()` selbst auf und legen die
# Extension damit an, bevor `get_connection()` sie braucht. Env aus conftest.py.


def test_init_db_is_idempotent() -> None:
    init_db()
    init_db()  # zweiter Aufruf darf nicht crashen (IF NOT EXISTS)


def test_init_db_creates_expected_chunks_schema() -> None:
    init_db()

    with get_connection() as conn:
        columns = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'chunks'
            ORDER BY ordinal_position;
            """
        ).fetchall()

    assert columns == [
        ("id", "bigint"),
        ("strategy", "text"),
        ("document_id", "text"),
        ("page", "integer"),
        ("content", "text"),
        ("embedding", "USER-DEFINED"),
    ]
