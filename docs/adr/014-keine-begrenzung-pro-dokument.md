# ADR 014: Keine Begrenzung pro Dokument

## Kontext

Multi-Hop-Fragen brauchen Belege aus zwei Handbüchern. Mit 20 Kandidaten
kommen davon 7 von 10 unter die Kandidaten, im Gesamtwert fehlen 6 von 36
Belegen. Die Annahme hinter `retrieve_per_document()`: Die Seiten eines
Handbuchs ähneln sich, füllen die Top `k` allein und verdrängen die Seite aus
dem zweiten Handbuch. Eine Obergrenze pro Handbuch würde ihr Platz schaffen.

Gemessen ohne Reranker auf Eval-Set v3 (`18d1e67`, festgehalten in `44f865d`),
je ein Lauf, weil die vollständige Suche deterministisch ist
([ADR 011](011-vollstaendige-suche-statt-hnsw.md)):

| Suche | Gesamt | Multi-Hop | Nachschlagen | Tabelle | Zeichnung |
|---|---:|---:|---:|---:|---:|
| global, `k=20` | 30 / 36 | 7 / 10 | 8 / 10 | 7 / 8 | 8 / 8 |
| höchstens 10 pro Dokument, `k=20` | 30 / 36 | 7 / 10 | 8 / 10 | 7 / 8 | 8 / 8 |
| höchstens 5 pro Dokument, `k=20` | 26 / 36 | 6 / 10 | 7 / 10 | 6 / 8 | 7 / 8 |
| höchstens 2 pro Dokument, `k=5` | 20 / 36 | 2 / 10 | 6 / 10 | 5 / 8 | 7 / 8 |
| global, `k=5` (`a2454fd`) | 22 / 36 | 2 / 10 | 7 / 10 | 6 / 8 | 7 / 8 |

Die Annahme trifft nicht zu. Im Lauf mit `k=50` (`a2454fd`) liegen die
fehlenden Belege auf Platz 33 bis 40 (q-007, q-015, q-028, q-035) oder gar nicht
unter den ersten 50 (q-008, q-021, q-032). Sie werden nicht von einem anderen
Handbuch verdrängt, sie sind der Frage für das Embedding-Modell zu unähnlich.
Eine Obergrenze kann nur die beste Seite eines Handbuchs nach vorne holen, und
die ist es bei diesen Belegen nicht.

## Entscheidung

Die Suche läuft ohne Begrenzung pro Dokument (`retrieve_global()`).
`retrieve_per_document()` bleibt als Option `--per-document` für weitere
Messungen, ist aber nicht Teil des Standardablaufs.

## Alternativen

- **Höchstens 10 pro Dokument.** Bringt nichts: Bei allen 36 Fragen stehen die
  Belege auf denselben Plätzen wie in der globalen Suche, die Grenze verdrängt
  keinen und holt keinen nach vorne.
- **Höchstens 5 oder weniger pro Dokument.** Wirft echte Treffer aus dem
  Haupthandbuch, an ihre Stelle rücken unpassende Seiten aus anderen Handbüchern.

## Konsequenzen

- Der Hebel für die fehlenden Belege liegt nicht in der Verteilung auf die
  Handbücher. Infrage kommen mehr Kandidaten (vier Belege liegen auf Platz 33
  bis 40), eine Zerlegung von Multi-Hop-Fragen in Teilfragen oder, für die drei
  Belege außerhalb der Top 50, eine bessere Extraktion. Keiner davon ist
  gemessen.
- Gemessen ist das für diesen Korpus aus sechs Handbüchern. Bei Handbüchern mit
  sehr vielen ähnlichen Seiten kann eine Obergrenze greifen.
