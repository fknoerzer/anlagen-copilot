"""Shared fixtures for the test suite."""

from collections.abc import Iterator

import psycopg
import pytest

from anlagen_copilot.db import get_connection
from anlagen_copilot.scripts.init_db import init_db
from anlagen_copilot.settings import Settings, get_settings

# Set explicitly instead of read from the local .env: mandatory fields without
# a default (openai_api_key, anthropic_api_key) would otherwise tie the tests to
# an existing .env and fail with a ValidationError in CI or a fresh clone.
# In pydantic-settings, environment variables take precedence over the .env.
_TEST_ENV = {
    "OPENAI_API_KEY": "dummy",
    "ANTHROPIC_API_KEY": "dummy",
    "AZURE_OPENAI_ENDPOINT": "https://example.com",
    "AZURE_OPENAI_API_KEY": "dummy",
    # connect_timeout is what keeps a missing Postgres from turning into a hang.
    # libpq waits indefinitely by default, so without it the wait is bounded only
    # by the OS TCP stack: measured 260s against a dead port, and `localhost`
    # resolves to both ::1 and 127.0.0.1, which psycopg tries in turn — so every
    # value here costs twice. Five seconds makes that 10s and a readable error.
    "POSTGRES_DSN": (
        "postgresql://anlagen_copilot:anlagen_copilot"
        "@localhost:5432/anlagen_copilot?connect_timeout=5"
    ),
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
        # The variables above cover the mandatory fields; this covers the six that
        # have defaults, which would otherwise still be read from the local .env —
        # green here and in CI for different reasons, and red the moment someone
        # edits their own .env.
        mp.setitem(Settings.model_config, "env_file", None)
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def db_available(_test_env: None) -> None:
    """Skips the database tests when no Postgres is listening.

    A clone without `docker compose up` should report skipped, not failed:
    a red suite reads as a broken project, and the missing container is not
    something the reader can tell apart from a real defect.

    `register_types=False` on purpose. The probe asks one question — is anyone
    answering on that port — and pgvector's `ProgrammingError` for a database
    without the extension is deliberately not an `OperationalError`, so that
    case keeps failing loudly instead of disappearing into a skip.

    The catch is nevertheless wider than the message suggests: a wrong password
    is an `OperationalError` too. Change the credentials in
    `docker-compose.yml` without changing `_TEST_ENV`, and these tests go quiet
    rather than red. That is the standing price of a skip fixture, and the
    reason the DSN above is hard-coded rather than read from the environment.
    """
    try:
        with get_connection(register_types=False):
            pass
    except psycopg.OperationalError:
        pytest.skip("no Postgres reachable — run `docker compose up -d`")


@pytest.fixture(scope="session")
def db_schema(_test_env: None, db_available: None) -> None:
    """Makes sure extension and schema exist before any test connects.

    Deliberately not `autouse`: `init_db()` needs a running Postgres instance,
    and the tests without a database dependency should pass without Docker.
    Depends on `db_available` so that `init_db()` is never the thing that
    discovers the missing container — it would raise where a skip belongs.

    The head start is needed because `get_connection()` calls
    `register_vector()` by default, which aborts with a ProgrammingError against
    a database without the pgvector extension. pytest collects `test_db.py`
    alphabetically before `test_init_db.py` — without this fixture the suite
    would therefore die on a fresh volume before anyone had created the schema.
    """
    init_db()
