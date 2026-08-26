"""Tests für db.py: Verbindung zur Datenbank."""

import pytest

from anlagen_copilot.db import get_connection

# Beide Tests verbinden mit dem Default `register_types=True` und brauchen
# deshalb die pgvector-Extension. Env-Setup kommt aus conftest.py.
pytestmark = pytest.mark.usefixtures("db_schema")


def test_executes_query() -> None:
    with get_connection() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_closes_after_with_block() -> None:
    with get_connection() as conn:
        pass
    assert conn.closed
