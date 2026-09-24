# ADR 002: Chunking-Strategie als Spalte in derselben Tabelle

## Kontext

Layoutbewusstes Chunking soll gegen eine Seite pro Chunk gemessen werden. Beide
Varianten müssen dafür gegen dasselbe Eval-Set und über dieselbe Suchfunktion
laufen.

## Entscheidung

`chunks` hat eine Spalte `strategy` (`naive` oder `advanced`) und einen
`UNIQUE (strategy, document_id, page)`-Constraint. Welche Strategie der Ingest
schreibt, kommt aus der Konfiguration (`INGEST_STRATEGY`), nicht aus einem
eigenen Codepfad. Die Suchfunktionen filtern mit `WHERE strategy = …`.

## Alternativen

- **Eine Tabelle oder Datenbank je Strategie.** Sauber getrennt, aber jede
  Abfrage und jedes Schema-Update wäre doppelt.

## Konsequenzen

- Beide Strategien lassen sich mit einem Parameter vergleichen, in der
  Evaluation wie später in der Oberfläche.
- **Erledigt durch [ADR 011](011-vollstaendige-suche-statt-hnsw.md):** Ohne
  Index filtert `WHERE strategy` innerhalb der vollständigen Suche. Kommt der
  Index zurück, gilt der folgende Punkt wieder.
  Der HNSW-Index kennt die Spalte nicht. `WHERE strategy` filtert
  erst nach dem Index-Scan. Solange nur `naive` in der Tabelle liegt, ist das
  folgenlos. Mit beiden Strategien kann eine Suche weniger oder schlechtere
  Treffer liefern, ohne dass etwas fehlschlägt. Das muss gelöst sein, bevor
  `advanced`-Daten geschrieben werden (partielle Indizes je Strategie oder
  iterative Index-Scans ab pgvector 0.8).
