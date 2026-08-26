import psycopg
from pgvector.psycopg import register_vector

from anlagen_copilot.settings import get_settings


def get_connection(register_types: bool = True) -> psycopg.Connection:
    """Öffnet eine neue Verbindung zur Postgres-DB."""
    dsn = str(get_settings().postgres_dsn)
    conn = psycopg.connect(dsn)
    if register_types:
        register_vector(conn)
    return conn
