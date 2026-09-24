# ADR 003: 1536 statt 3072 Embedding-Dimensionen

## Kontext

`text-embedding-3-large` liefert nativ 3072 Dimensionen. Der HNSW-Index von
pgvector erlaubt höchstens 2000. Das erste Schema mit `vector(3072)` scheiterte
beim Indexaufbau mit `ProgramLimitExceeded`.

## Entscheidung

Die Embeddings werden über den `dimensions`-Parameter der API auf 1536
Dimensionen gekürzt. Die Grenze erlaubt jeden Wert bis 2000; 1536 ist der
verbreitete Wert (die Dimension von `text-embedding-3-small`) und die Hälfte der
nativen Dimension. Gegen andere Werte bis 2000 ist er nicht verglichen.
`embedding_dimensions` ist in den Settings auf höchstens
2000 begrenzt (`Field(le=2000)`), ein höherer Wert scheitert beim Start und
nicht erst an der Datenbank.

## Alternativen

- **3072 Dimensionen ohne Index.** Vollständige Suche, bei gut 1300 Seiten machbar,
  skaliert aber nicht.
- **`halfvec` mit bis zu 4000 Dimensionen im HNSW-Index.** Nicht untersucht.
- **`text-embedding-3-small` mit nativ 1536 Dimensionen.** Nicht untersucht.

## Konsequenzen

- Modell, Dimension und Schema müssen zusammenpassen. `init_db()` legt die
  Tabelle mit `IF NOT EXISTS` an und passt eine bestehende nicht an. Eine
  Änderung der Dimension verlangt ein `DROP TABLE chunks`.
- Ob die Kürzung auf 1536 Dimensionen Recall kostet, ist nicht gemessen.
- Seit [ADR 011](011-vollstaendige-suche-statt-hnsw.md) gibt es keinen HNSW-Index mehr,
  die Grenze von 2000 greift damit nicht. Die 1536 bleiben, solange kein Gewinn
  durch mehr Dimensionen gemessen ist.
