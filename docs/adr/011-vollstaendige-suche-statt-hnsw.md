# ADR 011: Vollständige Suche statt HNSW-Index

## Kontext

Im ersten Lauf gegen Eval-Set v2 (`2ac65fd`, nur Vektorsuche, `k=5`) hatte
q-036 einen `best_score` von genau `0.0`: Die Suche hatte keine einzige Seite
zurückgegeben. Die Ursache liegt nicht in der Frage, sondern im Plan:

- Bei `LIMIT 5` wählt PostgreSQL den HNSW-Index, ab `LIMIT 10` einen Seq Scan
  mit Sortierung. Geprüft über alle 36 Fragen und `k` = 5, 10, 15, 20, 30, 50.
  Der Planer kannte die richtige Zeilenzahl (`reltuples = 1322`); er rechnet
  nur nicht damit, dass der Index weniger Zeilen liefert als verlangt.
- Mit dem Standardwert `hnsw.ef_search = 40` liefert der Index bei drei von 36
  Fragen weniger als fünf Zeilen: q-028 drei, q-031 eine, q-036 keine. Bei
  q-031 geht dabei die Belegseite verloren, die bei vollständiger Suche auf Platz 2 steht.
- Das Protokoll verrät eine zu kurze Liste nur, wenn sie ganz leer ist. Eine
  Liste mit drei statt fünf Seiten sieht im Ergebnis aus wie ein gewöhnlicher
  Fehltreffer.

Vergleich über alle 36 v2-Fragen, `k=5`, Stand `2ac65fd`, 1.322 Seiten in
`chunks`. Zeit ist die reine Datenbankabfrage (lokal in Docker), je Frage der
Median aus drei Wiederholungen, davon der Median über alle Fragen. Der
HNSW-Plan ist in allen HNSW-Zeilen erzwungen (`enable_seqscan`,
`enable_bitmapscan` und `enable_sort` aus):

| Suche | Belegseiten Top 5 | Zu kurze Listen | Übereinstimmung mit vollständig | Median je Abfrage |
|---|---:|---:|---:|---:|
| vollständig (Seq Scan) | 17 / 36 | 0 | 180 / 180 | 9,1 ms |
| HNSW, `ef_search` 40 | 16 / 36 | 3 | 166 / 180 | 1,0 ms |
| HNSW, `ef_search` 100 | 17 / 36 | 0 | 180 / 180 | 9,2 ms |
| HNSW, `ef_search` 40, `iterative_scan = strict_order` | 17 / 36 | 0 | 180 / 180 | 8,9 ms |

Bei dieser Korpusgröße ist der Index nur dann schneller, wenn er Seiten
verliert. Arbeitet er zuverlässig, liefert er dasselbe wie die vollständige Suche in
derselben Zeit. Der Embedding-Aufruf davor dauert rund 0,2 s je Frage, mehr als
das Zwanzigfache der Datenbankabfrage.

## Entscheidung

Die Vektorsuche läuft als vollständige Suche: Jede Seite wird mit der Frage
verglichen, die Treffer sind die tatsächlich nächsten Nachbarn (exaktes k-NN,
im Gegensatz zur genäherten Suche über einen ANN-Index). Der HNSW-Index
`chunks_embedding_hnsw_idx` entfällt. Ohne ihn bleibt dem Planer für die
Sortierung nach Ähnlichkeit nur die vollständige Suche, unabhängig von `k`.
`init_db()` legt ihn nicht mehr an und entfernt ihn aus einer bestehenden
Datenbank (`DROP INDEX IF EXISTS`), weil `IF NOT EXISTS` eine alte Tabelle
sonst unverändert ließe.

Der Index kommt zurück, wenn die vollständige Suche im Median über 50 ms je Abfrage
braucht, also ein Viertel des Embedding-Aufrufs. Dann mit
`hnsw.iterative_scan = strict_order` und erst, nachdem derselbe Vergleich
gegen die vollständige Suche gezeigt hat, dass er keine Belegseiten kostet.

## Alternativen

- **`ef_search` erhöhen.** Mit 100 verschwindet der Fehler hier, aber niemand
  weiß, ob 100 für die nächste Frage oder den nächsten Korpus reicht. Und der
  Zeitvorteil ist mit dem Fehler weg.
- **Iterativer Scan (`hnsw.iterative_scan`, ab pgvector 0.8).** Liefert
  garantiert `LIMIT` Zeilen und ist hier ebenso gut wie die vollständige Suche. Bleibt aber
  approximativ, also eine Streuungsquelle in jedem Lauf, ohne messbaren Gewinn.
  Der vorgesehene Weg, sobald der Index wieder gebraucht wird.
- **Index behalten, den Plan dem Planer überlassen.** Dann hängt die
  Suchqualität an `k` und an der Tabellenstatistik, ohne dass ein Lauf es
  anzeigt. Genau das hat diesen Befund verdeckt.

## Konsequenzen

- Die Vektorsuche ist deterministisch. Läufe ohne Reranker brauchen keine
  Wiederholung mehr für eine Spanne; die Streuung der Reranking-Läufe kommt
  allein vom Reranker.
- Betroffen waren nur Läufe, die über den Index liefen, nach heutigem Plan also
  `k=5` ohne Reranker: `2ac65fd` in v2, `9db58dc` und `6e766d3` in v1. Die
  Reranking-Läufe holen 20 und mehr Kandidaten und liefen vollständig. Welchen Plan
  die v1-Läufe damals tatsächlich hatten, lässt sich nachträglich nicht prüfen.
- Die 1536 Dimensionen bleiben. Ihr Grund in [ADR 003](003-embedding-dimensionen.md),
  die Grenze von 2000 Dimensionen im HNSW-Index, gilt ohne Index nicht mehr.
  3072 wieder zu öffnen hieße, alle Embeddings neu zu erzeugen, ohne dass ein
  Gewinn gemessen ist. Kommt der Index zurück, gilt die Grenze wieder.
- [ADR 009](009-pgvector.md) bleibt bei PostgreSQL mit pgvector; nur der Index
  entfällt. Die Konsequenz dort, dass der Filter auf `strategy` erst nach dem
  Indexscan greift, betrifft die vollständige Suche nicht.
- **Offen:** Der Vergleich lief als Skript außerhalb des Repos. Für die
  Rückkehr des Index gehört er als wiederholbares Skript ins Repo.
