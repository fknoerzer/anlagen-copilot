# ADR 012: Strukturierte Ausgabe statt erzwungenem Tool-Call

## Kontext

Der Reranker holte seine Noten über einen erzwungenen Tool-Call
([ADR 004](004-reranker-ausgabe.md)): ein Tool `record_grades`, das nie
ausgeführt wird, und `tool_choice`, das seinen Aufruf erzwingt. Das
`input_schema` eines Tools beschreibt die Struktur aber nur, es setzt sie nicht
durch. Beide Pannen aus ADR 004 kommen daher:

- Das Modell brach das Schema mit IDs gelegentlich. Der Umweg über Noten nach
  Position (`c0928ff`) senkte den Anteil gefundener Belegseiten auf v1 von
  66,7 % auf 58,3 % und wurde zurückgenommen (`1f4d839`).
- Beim längsten Prompt kam die Liste in 3 von 8 Aufrufen als String ohne
  schließende Klammer. Eine eigene Reparatur ergänzte die Klammer.

Dazu kommt: Neuere Modelle lehnen einen erzwungenen `tool_choice` mit 400 ab
(Claude Opus 5.5, Claude Fable 5.1). Die Generierung braucht ebenfalls eine
Antwort in fester Form.

## Entscheidung

Die Noten kommen als strukturierte Ausgabe (`output_config.format`). Die API
setzt das Schema beim Erzeugen der Tokens durch, eine Liste in falscher Form
kann nicht entstehen. Das Schema wird mit `anthropic.transform_schema` aus dem
Pydantic-Modell `_Grades` gebaut, Struktur und Prüfung sind also eine einzige
Beschreibung. Haiku 4.5 unterstützt strukturierte Ausgabe.

Der Aufruf läuft über `messages.create()`. Danach wird zuerst `stop_reason`
geprüft (nur `end_turn` gilt als fertig), dann der Text mit
`_Grades.model_validate_json()` validiert. Das Format mit Seiten-ID aus
ADR 004 bleibt unverändert. Die Klammer-Reparatur entfällt.

## Alternativen

- **`messages.parse()` mit dem Modell als `output_format`.** Weniger Code, aber
  `parse()` validiert den Text, bevor `stop_reason` geprüft werden kann. Eine
  durch `max_tokens` abgeschnittene Antwort käme als JSON-Fehler an statt mit
  dem Abbruchgrund.
- **Tool mit `strict: true`.** Setzt das Schema ebenfalls durch, bleibt aber ein
  zweckentfremdeter Tool-Call, und das Schema stünde weiter doppelt da, von Hand
  im Tool und im Pydantic-Modell.
- **Beim erzwungenen Tool-Call bleiben.** Die Reparatur müsste bleiben, und der
  Wechsel auf neuere Modelle wäre versperrt.

## Konsequenzen

- Der Docstring eines Modells, das ins Schema geht, wird dort zur
  `description` und bei jedem Aufruf mitgelesen. Er bleibt einzeilig und
  richtet sich an das Modell; Begründungen für Entwickler stehen als Kommentar
  daneben.
- Im Schema sind `enum` erlaubt, `minimum` und `maximum` nicht. Die Noten 0–3
  gehen als `enum`, Grenzen wie der Bereich der Seiten-IDs müssen im Code
  geprüft werden.
- Der erste Aufruf mit einem neuen Schema ist langsamer, weil die API die
  Grammatik kompiliert. Danach ist sie 24 Stunden zwischengespeichert.
- Geprüft ist bisher nur, dass ein echter Aufruf das Schema annimmt
  (Probelauf, 2026-09-26).
- **Offen:** Die Messung. Drei Läufe mit 20 Kandidaten gegen die Spanne 23–23
  auf `fc391fd`. Erwartung vorher: 23 ± 1 Belegseiten und Output-Tokens um
  11.400 je Lauf, weil sich die Form der Noten nicht ändert. Das Ergebnis wird
  hier nachgetragen.
