"""Tests für db.py: Verbindung zur Datenbank."""

import pytest

from anlagen_copilot.config import get_settings
from anlagen_copilot.db import get_connection


@pytest.fixture(autouse=True)
def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql://anlagen_copilot:anlagen_copilot@localhost:5432/anlagen_copilot",
    )
    get_settings.cache_clear()


def test_executes_query() -> None:
    with get_connection() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_closes_after_with_block() -> None:
    with get_connection() as conn:
        pass
    assert conn.closed
