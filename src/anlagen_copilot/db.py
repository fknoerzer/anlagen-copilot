import logging

import psycopg
from pgvector.psycopg import register_vector
from pydantic import PostgresDsn

from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def _target(dsn: PostgresDsn) -> str:
    """Describes the connection target without credentials, for log messages.

    `str(dsn)` carries user and password in plain text and must therefore never
    reach the log — not even at DEBUG: log files outlive the session that
    produced them and travel on into tickets, CI artefacts and backups.
    """
    host = dsn.hosts()[0]
    return f"{host['host']}:{host['port'] or 5432}{dsn.path or ''}"


def get_connection(register_types: bool = True) -> psycopg.Connection:
    """Opens a new connection to the Postgres database."""
    dsn = get_settings().postgres_dsn
    logger.debug("Connecting to %s (register_types=%s)", _target(dsn), register_types)
    conn = psycopg.connect(str(dsn))
    if register_types:
        register_vector(conn)
    return conn
