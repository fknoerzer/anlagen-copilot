# ADR 001: Eine Seite = ein Chunk

## Kontext

Jede Antwort soll ihre Quelle auf die Seite genau belegen. Die Handbücher sind
seitenweise aufgebaut: Eine Tabelle, eine Explosionszeichnung oder ein
Störungseintrag steht meist auf einer Seite. Das Embedding-Modell nimmt bis zu
8191 Tokens; die dichteste Seite im Korpus hat 2383 Tokens, der Median liegt bei
878.

## Entscheidung

Jede PDF-Seite wird genau ein Chunk. Die Seitennummer bleibt die des Originals,
auch bei einem Auszug (`excerpt_pages`): Seite 501 des Listenhandbuchs bleibt 501
und wird nicht auf 49 umnummeriert. Zeilen, die auf mindestens 85 % der Seiten
eines Dokuments wiederkehren (Kopf- und Fußzeilen), werden vorher entfernt,
bei Dokumenten ab 10 Seiten.

## Alternativen

- **Chunks fester Tokenlänge mit Überlappung.** Übliches Vorgehen, aber ein
  Chunk kann dann über eine Seitengrenze reichen, und die Quellenangabe wird
  ungenau.
- **Layoutbewusstes Chunking (Docling oder Azure Document Intelligence, noch
  offen).** Geplant als `advanced`-Strategie
  (siehe [ADR 002](002-strategie-als-spalte.md)), um gegen diese Grundlinie
  gemessen zu werden.

## Konsequenzen

- Chunk und PDF-Seite entsprechen sich 1:1. Ein Link mit `#page=N` ist damit
  eine vollständige Quellenangabe.
- Keine Seite liegt über dem Embedding-Limit (0 von 1322), ein Guard dafür ist
  nicht nötig.
- Die Seiten eines Handbuchs sehen sich ähnlich, eine Vektorsuche findet eher
  das Thema als die Seite mit der Antwort. Das Reranking
  ([ADR 004](004-reranker-ausgabe.md)) setzt hier an.
- Tabellen verlieren bei der Textextraktion ihre Spaltenstruktur. Bei q-018 ist
  die Zuordnung Marke zu Getriebevariante nach der Extraktion nicht mehr
  erkennbar. Das ist der gemessene Anlass für die `advanced`-Strategie.
