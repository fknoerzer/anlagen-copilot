from anlagen_copilot.db import get_connection

_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector;",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id BIGSERIAL PRIMARY KEY,
        document_id TEXT NOT NULL,
        page INTEGER,
        content TEXT NOT NULL,
        embedding VECTOR(3072) NOT NULL
    );
    """,
)


def init_db() -> None:
    """Aktiviert die pgvector-Extension und legt die chunks-Tabelle an.

    Idempotent (IF NOT EXISTS überall) — gefahrlos mehrfach ausführbar,
    z. B. nach einem frischen `docker compose up -d`.
    """
    with get_connection() as conn:
        for statement in _STATEMENTS:
            conn.execute(statement)


if __name__ == "__main__":
    init_db()
