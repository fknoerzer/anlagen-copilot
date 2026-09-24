# ADR 009: PostgreSQL mit pgvector als Vektordatenbank

## Kontext

Die Seiten brauchen eine Vektorsuche, aber auch relationale Eigenschaften: eine
`strategy`-Spalte mit `UNIQUE`-Constraint ([ADR 002](002-strategie-als-spalte.md))
und den atomaren Austausch aller Chunks eines Dokuments
([ADR 006](006-transaktion-pro-dokument.md)). Das Projekt läuft lokal und in
CI, ohne Cloud-Konto. Womit die layoutbewusste Ingestion
laufen soll (Docling oder Azure Document Intelligence), ist noch offen.

## Entscheidung

PostgreSQL 16 mit der Extension pgvector (Image `pgvector/pgvector:pg16`).
Text, Dokument-ID, Seitennummer, Strategie und Embedding einer Seite liegen in
derselben Zeile der Tabelle `chunks`, durchsucht über einen HNSW-Index mit Cosinus-Distanz.
Der Index ist durch [ADR 011](011-vollstaendige-suche-statt-hnsw.md) abgelöst: Die Suche
läuft vollständig, pgvector bleibt.

## Alternativen

- **Azure AI Search.** Braucht ein Azure-Konto und läuft nur als Cloud-Dienst,
  ohne lokalen Container für Entwicklung und CI. Als Vergleich in einem eigenen
  Azure-Zweig denkbar.
- **Eigenständige Vektordatenbank (Qdrant, Chroma, Weaviate).** Nicht
  untersucht. Die Transaktion pro Dokument und der `UNIQUE`-Constraint müssten
  dort anders gelöst werden.

## Konsequenzen

- Lokal reicht ein `docker compose up`, in CI ein Service-Container mit
  demselben Image.
- Schema, Constraints und Suche sind SQL und lassen sich mit `EXPLAIN` prüfen.
- Der HNSW-Index nimmt höchstens 2000 Dimensionen
  ([ADR 003](003-embedding-dimensionen.md)).
- Der Index kennt die `strategy`-Spalte nicht, der Filter greift erst nach dem
  Scan ([ADR 002](002-strategie-als-spalte.md)).
- **Offen:** Das Image-Tag `pg16` folgt der jeweils neuesten pgvector-Version.
  Ein `docker compose pull` kann eine andere unterschieben.
