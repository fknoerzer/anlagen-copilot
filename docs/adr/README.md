# Architecture Decision Records

Jede Datei hält eine Entscheidung fest: Kontext, Entscheidung, verworfene
Alternativen und Konsequenzen.

| Nr. | Entscheidung |
|---|---|
| [001](001-seite-als-chunk.md) | Eine Seite = ein Chunk |
| [002](002-strategie-als-spalte.md) | Chunking-Strategie als Spalte in derselben Tabelle |
| [003](003-embedding-dimensionen.md) | 1536 statt 3072 Embedding-Dimensionen |
| [004](004-reranker-ausgabe.md) | Reranker-Ausgabe mit Seiten-ID (Mechanismus abgelöst durch 012) |
| [005](005-kein-stiller-rueckfall.md) | Kein stiller Rückfall auf die Reihenfolge der Vektorsuche |
| [006](006-transaktion-pro-dokument.md) | Eine Transaktion pro Dokument |
| [007](007-konfiguration-vorab-pruefen.md) | Embedding-Konfiguration vor dem ersten Download prüfen |
| [008](008-eval-laeufe-protokollieren.md) | Jeder Eval-Lauf wird mit seiner Konfiguration protokolliert |
| [009](009-pgvector.md) | PostgreSQL mit pgvector als Vektordatenbank |
| [010](010-kein-rag-framework.md) | Kein RAG-Framework |
| [011](011-vollstaendige-suche-statt-hnsw.md) | Vollständige Suche statt HNSW-Index |
| [012](012-strukturierte-ausgabe.md) | Strukturierte Ausgabe statt erzwungenem Tool-Call |
| [013](013-antworten-als-aussagen.md) | Antworten als Aussagen mit Seiten-IDs |
