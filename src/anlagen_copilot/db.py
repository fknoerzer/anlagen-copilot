import psycopg

from anlagen_copilot.config import get_settings


def get_connection() -> psycopg.Connection:
    """Öffnet eine neue Verbindung zur Postgres-DB.

    TODO: aktuell eine Verbindung pro Aufruf. Sinnvoll für einen ersten
    Verbindungstest, aber siehe Diskussion zu psycopg_pool für den
    späteren Ingestion-/Retrieval-Code.
    """
    dsn = str(get_settings().postgres_dsn)
    return psycopg.connect(dsn)
