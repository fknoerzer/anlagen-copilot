"""Gemeinsame Fixtures für die Testsuite."""

from collections.abc import Iterator

import pytest

from anlagen_copilot.scripts.init_db import init_db
from anlagen_copilot.settings import get_settings

# Explizit gesetzt statt aus der lokalen .env gelesen: Pflichtfelder ohne Default
# (openai_api_key, anthropic_api_key) würden die Tests sonst an eine vorhandene
# .env koppeln und in CI oder einem frischen Klon mit ValidationError abbrechen.
# Env-Variablen haben in pydantic-settings Vorrang vor der .env-Datei.
_TEST_ENV = {
    "OPENAI_API_KEY": "dummy",
    "ANTHROPIC_API_KEY": "dummy",
    "AZURE_OPENAI_ENDPOINT": "https://example.com",
    "AZURE_OPENAI_API_KEY": "dummy",
    "POSTGRES_DSN": "postgresql://anlagen_copilot:anlagen_copilot@localhost:5432/anlagen_copilot",
}


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> Iterator[None]:
    """Setzt die Test-Env für die gesamte Session.

    `monkeypatch` ist function-scoped und in einer session-scoped Fixture nicht
    verwendbar (ScopeMismatch), daher der explizite Kontextmanager.

    Der Cache wird auf beiden Seiten geleert: beim Aufbau, damit die gepatchten
    Werte greifen, beim Abbau, damit kein Settings-Objekt mit Testwerten
    zurückbleibt — die Env-Variablen nimmt der Kontextmanager zurück, das
    gecachte Objekt nicht.
    """
    with pytest.MonkeyPatch.context() as mp:
        for key, value in _TEST_ENV.items():
            mp.setenv(key, value)
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def db_schema(_test_env: None) -> None:
    """Stellt sicher, dass Extension und Schema existieren, bevor ein Test verbindet.

    Bewusst nicht `autouse`: `init_db()` braucht eine laufende Postgres-Instanz,
    und die Tests ohne Datenbankbezug sollen ohne Docker durchlaufen.

    Nötig ist der Vorlauf, weil `get_connection()` per Default `register_vector()`
    aufruft, das auf einer Datenbank ohne pgvector-Extension mit ProgrammingError
    abbricht. pytest sammelt `test_db.py` alphabetisch vor `test_init_db.py` ein —
    ohne diese Fixture stirbt die Suite auf einem frischen Volume also, bevor
    irgendjemand das Schema angelegt hat.
    """
    init_db()
