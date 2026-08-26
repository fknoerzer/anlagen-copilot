from anlagen_copilot.db import get_connection
from anlagen_copilot.settings import get_settings


def _statements(dimensions: int) -> tuple[str, ...]:
    """Baut die DDL-Statements für die angegebene Embedding-Dimension.

    Bewusst eine Funktion statt einer Modulkonstante: `dimensions` kommt aus den
    Settings, und die sollen erst bei Benutzung gebaut werden, nicht beim Import
    dieses Moduls.

    `dimensions` wird in den String interpoliert statt als Query-Parameter
    übergeben — ein Typ-Modifier wie `VECTOR(n)` ist in DDL nicht
    parametrisierbar. Unbedenklich, weil Pydantic den Wert bereits als `int`
    validiert hat.
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
    """Aktiviert die pgvector-Extension und legt die chunks-Tabelle an.

    Idempotent (IF NOT EXISTS überall) — gefahrlos mehrfach ausführbar,
    z. B. nach einem frischen `docker compose up -d`.

    Achtung: `IF NOT EXISTS` heißt auch, dass eine bereits vorhandene Tabelle
    *nicht* an eine geänderte `embedding_dimensions` angepasst wird. Der
    Unterschied fällt dann erst beim HNSW-Index oder beim `INSERT` auf.
    """
    with get_connection(register_types=False) as conn:
        for statement in _statements(get_settings().embedding_dimensions):
            conn.execute(statement)


if __name__ == "__main__":
    init_db()
