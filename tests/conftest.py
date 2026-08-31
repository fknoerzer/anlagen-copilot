"""Shared fixtures for the test suite."""

from collections.abc import Iterator

import pytest

from anlagen_copilot.scripts.init_db import init_db
from anlagen_copilot.settings import get_settings

# Set explicitly instead of read from the local .env: mandatory fields without
# a default (openai_api_key, anthropic_api_key) would otherwise tie the tests to
# an existing .env and fail with a ValidationError in CI or a fresh clone.
# In pydantic-settings, environment variables take precedence over the .env.
_TEST_ENV = {
    "OPENAI_API_KEY": "dummy",
    "ANTHROPIC_API_KEY": "dummy",
    "AZURE_OPENAI_ENDPOINT": "https://example.com",
    "AZURE_OPENAI_API_KEY": "dummy",
    "POSTGRES_DSN": "postgresql://anlagen_copilot:anlagen_copilot@localhost:5432/anlagen_copilot",
}


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> Iterator[None]:
    """Sets the test environment for the whole session.

    `monkeypatch` is function-scoped and unusable inside a session-scoped
    fixture (ScopeMismatch), hence the explicit context manager.

    The cache is cleared on both sides: on setup so the patched values take
    effect, on teardown so no Settings object with test values is left behind —
    the context manager takes the environment variables back, the cached object
    it does not.
    """
    with pytest.MonkeyPatch.context() as mp:
        for key, value in _TEST_ENV.items():
            mp.setenv(key, value)
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def db_schema(_test_env: None) -> None:
    """Makes sure extension and schema exist before any test connects.

    Deliberately not `autouse`: `init_db()` needs a running Postgres instance,
    and the tests without a database dependency should pass without Docker.

    The head start is needed because `get_connection()` calls
    `register_vector()` by default, which aborts with a ProgrammingError against
    a database without the pgvector extension. pytest collects `test_db.py`
    alphabetically before `test_init_db.py` — without this fixture the suite
    would therefore die on a fresh volume before anyone had created the schema.
    """
    init_db()
