# ADR 004: Reranker-Ausgabe als erzwungener Tool-Call mit Seiten-ID

> Den Mechanismus löst [ADR 012](012-strukturierte-ausgabe.md) ab: strukturierte
> Ausgabe statt erzwungenem Tool-Call, ohne Klammer-Reparatur. Das Format mit
> Seiten-ID und die Messung dazu gelten weiter.

## Kontext

Der Reranker bewertet bis zu 20 Kandidatenseiten mit einer Relevanzstufe von 0
bis 3. Die Stufen müssen maschinenlesbar und eindeutig einer Seite zugeordnet
zurückkommen.

## Entscheidung

Das Modell muss das Tool `record_grades` aufrufen (`tool_choice` erzwungen). Es
nennt für jede Seite ihre ID und die Stufe:
`[{"id": 1, "grade": 3}, {"id": 2, "grade": 0}, …]`. Die Antwort wird mit
Pydantic validiert (`extra="forbid"`, `strict=True`): Eine Stufe als String
(`"3"`) wird abgelehnt, nicht umgewandelt. Sortiert wird nach Stufe, innerhalb einer
Stufe nach Vektor-Score.

Eine einzige Abweichung wird repariert: Bei langen Prompts lieferte das Modell
die Liste in 3 von 8 Aufrufen als String mit fehlender schließender Klammer.
Nur diese Klammer wird ergänzt, ein Komma davor wird entfernt. Alles andere bricht den Lauf ab
([ADR 005](005-kein-stiller-rueckfall.md)).

## Alternativen

- **Freitext mit Parsing.** Fehleranfällig, kein Schema.
- **Stufen nach Position** (`[3, 0, 2, …]`, die n-te Zahl gehört zur n-ten
  Seite). Eingeführt mit `c0928ff`, weil das Modell das Schema mit IDs
  gelegentlich brach, und gemessen:

  | Format | Output-Tokens je Lauf | Anteil gefundener Belegseiten |
  |---|---:|---:|
  | Mit Seiten-ID (`4d187b6`) | 11.620 | 66,7 % |
  | Nach Position (`c0928ff`) | 3.312 | 58,3 % |

  Das Modell vergab im Positionsformat überwiegend Nullen, der Reranker
  änderte die Reihenfolge kaum noch. Die 58,3 % liegen unter der Spanne, die drei Läufe im ID-Format
  erreichen (66,7–69,4 %), der Abstand ist also größer als die Streuung.
  Zurückgenommen mit `1f4d839`, dessen Lauf das ID-Format bestätigt.

## Konsequenzen

- Etwa dreieinhalbmal so viele Output-Tokens wie im Positionsformat.
- `max_tokens` wächst mit der Kandidatenzahl (`128 + 64 × n`), damit die Liste
  nicht abgeschnitten wird.
- Eine Seite, die das Modell nicht bewertet, bekommt Stufe 0 und eine Warnung.
  Eine unbekannte ID wird ignoriert.
