"""Tests für scripts/init_db.py: Schema-Setup (Extension + chunks-Tabelle)."""

import pytest

from anlagen_copilot.config import get_settings
from anlagen_copilot.db import get_connection
from anlagen_copilot.scripts.init_db import init_db


@pytest.fixture(autouse=True)
def _db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "dummy")
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql://anlagen_copilot:anlagen_copilot@localhost:5432/anlagen_copilot",
    )
    get_settings.cache_clear()


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
        ("document_id", "text"),
        ("page", "integer"),
        ("content", "text"),
        ("embedding", "USER-DEFINED"),
    ]
