"""Tests for scripts/init_db.py: schema setup (extension + chunks table)."""

import pytest

from anlagen_copilot.db import get_connection
from anlagen_copilot.scripts.init_db import init_db

# No `db_schema` needed: both tests call `init_db()` themselves and create the
# extension that way before `get_connection()` needs it. Env from conftest.py.
# `db_available` is needed all the same — these two reach for Postgres from the
# test body, where a missing container would fail rather than skip.
pytestmark = [pytest.mark.usefixtures("db_available"), pytest.mark.integration]


def test_init_db_is_idempotent() -> None:
    init_db()
    init_db()  # a second call must not crash (IF NOT EXISTS)


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
