# ADR 008: Jeder Eval-Lauf wird mit seiner Konfiguration protokolliert

## Kontext

Eine einzelne Recall-Zahl ist ohne ihre Konfiguration nicht einzuordnen. Schon
der erste Vergleich zweier Läufe mit verschiedenem `k` wäre sonst falsch
gewesen.

## Entscheidung

Jeder Lauf wird als eine Zeile an `data/eval_runs.jsonl` angehängt: Zeitstempel,
Commit-Hash, Strategie, `k`, Begrenzung pro Dokument, Kandidatenzahl,
Reranker-Modell, Embedding-Modell und -Dimension, Token-Verbrauch und die
Ergebnisse pro Frage. Jede Zeile ist ein validiertes Pydantic-Modell
(`EvalRun`); dass sie sich verlustfrei zurücklesen lässt, sichern Tests ab.
Ein Auswertungsskript, das die Reihe zurückliest, gibt es noch nicht.

## Alternativen

- **Nur Gesamtwerte speichern.** Aus Einzelergebnissen lassen sich Gesamtwerte
  jederzeit neu berechnen, umgekehrt nicht. Und „welche Frage ist schlechter
  geworden" ist die Frage, die die nächste Arbeit lenkt.
- **Experiment-Tracking-Werkzeug (z. B. MLflow).** Für eine Datei mit einigen
  Dutzend Zeilen zu schwer.

## Konsequenzen

- Jede Zahl in der README lässt sich auf einen Lauf zurückführen.
- Neue Felder brauchen einen Default oder werden in den älteren Zeilen
  nachgetragen, damit diese lesbar bleiben. Nachgetragen ist bisher nur
  `eval_set_version`, weil der Wert für alle alten Zeilen bekannt war (`v1`).
- Welcher Stand des Eval-Sets gemessen wurde, steht als `eval_set_version` in
  jeder Zeile, gepflegt als `version` in `data/eval_set.yaml`.
