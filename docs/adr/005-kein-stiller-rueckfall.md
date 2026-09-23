# ADR 005: Kein stiller Rückfall auf die Reihenfolge der Vektorsuche

## Kontext

Der Reranker kann kein verwertbares Ergebnis liefern: Abbruch durch
`max_tokens`, kein Tool-Call, Werte außerhalb des Schemas. Der naheliegende
Ausweg wäre, dann die Reihenfolge der Vektorsuche zu übernehmen.

## Entscheidung

Ein ungültiges Ergebnis beendet den Lauf mit einem Fehler (`ValueError` bzw.
`pydantic.ValidationError`).

## Alternativen

- **Rückfall auf die Vektor-Reihenfolge.** Bequemer, aber der Eval-Lauf
  protokolliert dann eine Messung, die nach Reranking aussieht und keines ist.
  Gerade die Evaluation soll zeigen, was das Reranking bringt.

## Konsequenzen

- Ein langer Eval-Lauf kann an einem einzelnen Aufruf scheitern und muss
  wiederholt werden.
- Die Messreihe enthält nur echte Reranking-Ergebnisse.
- Ein Reranker, der nichts mehr umsortiert, fällt trotzdem auf: Vergibt er
  überall Stufe 0, kommt die reine Vektor-Reihenfolge heraus. So wurde Lauf 11
  erkannt ([ADR 004](004-reranker-ausgabe.md)).
- **Offen:** Für eine Nutzeroberfläche kann ein Rückfall mit Hinweis die
  bessere Wahl sein als ein Fehler. Die Entscheidung gilt für die Evaluation
  und ist für den späteren Endpunkt neu zu treffen.
