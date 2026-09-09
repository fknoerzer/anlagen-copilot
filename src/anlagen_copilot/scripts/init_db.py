"""Schema setup for the `chunks` table and the pgvector extension.

Runs once before any ingestion and is idempotent, so a fresh container and a
database that already holds chunks take the same path.
"""

import logging

from anlagen_copilot.db import get_connection
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def _statements(dimensions: int) -> tuple[str, ...]:
    """Build the DDL statements for the given embedding dimension.

    Deliberately a function rather than a module constant: `dimensions` comes
    from the settings, and those are meant to be built on use, not when this
    module is imported.

    `dimensions` is interpolated into the string instead of passed as a query
    parameter — a type modifier such as `VECTOR(n)` cannot be parameterised in
    DDL. Harmless, because pydantic has already validated the value as an
    `int`.
    """
    return (
        "CREATE EXTENSION IF NOT EXISTS vector;",
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id BIGSERIAL PRIMARY KEY,
            strategy TEXT NOT NULL,
            document_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding VECTOR({dimensions}) NOT NULL,
            UNIQUE (strategy, document_id, page)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
        ON chunks USING hnsw (embedding vector_cosine_ops);
        """,
    )


def init_db() -> None:
    """Enable the pgvector extension and create the chunks table.

    Idempotent (IF NOT EXISTS throughout) — safe to run repeatedly, e.g. after
    a fresh `docker compose up -d`.

    Careful: `IF NOT EXISTS` also means an existing table is *not* adjusted to
    a changed `embedding_dimensions`. The difference then only surfaces at the
    HNSW index or at the `INSERT`.
    """
    dimensions = get_settings().embedding_dimensions
    logger.info("Creating schema (embedding_dimensions=%d), idempotent", dimensions)

    with get_connection(register_types=False) as conn:
        for statement in _statements(dimensions):
            conn.execute(statement)
            logger.debug("DDL executed: %s", statement.strip().splitlines()[0])


# setup_logging() sits here rather than in init_db(): that function is also
# called from the db_schema fixture in tests/conftest.py, and a test run should
# not have its logging configuration changed for it by a helper.
if __name__ == "__main__":
    setup_logging()
    init_db()
