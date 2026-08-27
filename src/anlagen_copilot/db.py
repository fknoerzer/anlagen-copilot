import logging

import psycopg
from pgvector.psycopg import register_vector
from pydantic import PostgresDsn

from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def _target(dsn: PostgresDsn) -> str:
    """Beschreibt das Verbindungsziel ohne Zugangsdaten, für Logmeldungen.

    `str(dsn)` enthält Benutzer und Passwort im Klartext und darf deshalb nie
    ins Log — auch nicht auf DEBUG: Logdateien überleben die Session, in der sie
    entstanden sind, und wandern in Tickets, CI-Artefakte und Backups.
    """
    host = dsn.hosts()[0]
    return f"{host['host']}:{host['port'] or 5432}{dsn.path or ''}"


def get_connection(register_types: bool = True) -> psycopg.Connection:
    """Öffnet eine neue Verbindung zur Postgres-DB."""
    dsn = get_settings().postgres_dsn
    logger.debug("Connecting to %s (register_types=%s)", _target(dsn), register_types)
    conn = psycopg.connect(str(dsn))
    if register_types:
        register_vector(conn)
    return conn
