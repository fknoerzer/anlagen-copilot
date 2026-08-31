"""Tests for db.py: connecting to the database."""

import pytest

from anlagen_copilot.db import get_connection

# Both tests connect with the default `register_types=True` and therefore need
# the pgvector extension. Env setup comes from conftest.py.
pytestmark = pytest.mark.usefixtures("db_schema")


def test_executes_query() -> None:
    with get_connection() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_closes_after_with_block() -> None:
    with get_connection() as conn:
        pass
    assert conn.closed
