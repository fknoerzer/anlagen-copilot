# ADR 008: Jeder Eval-Lauf wird mit seiner Konfiguration protokolliert

## Kontext

Eine einzelne Recall-Zahl ist ohne ihre Konfiguration nicht einzuordnen. Schon
der erste Vergleich zweier Läufe mit verschiedenem `k` wäre sonst falsch
gewesen.

## Entscheidung

Jeder Lauf wird als eine Zeile angehängt, Retrieval-Läufe an
`data/retrieval/eval_runs.jsonl`, Antwort-Läufe an
`data/generation/eval_runs.jsonl`: Zeitstempel, Commit-Hash, Version des
Eval-Sets, Strategie, `k`, Begrenzung pro Dokument, Kandidatenzahl,
Reranker-Modell und -Temperatur, Embedding-Modell und -Dimension,
Token-Verbrauch und die Ergebnisse pro Frage, bei Antwort-Läufen dazu das
Generierungsmodell. Jede Zeile ist ein validiertes Pydantic-Modell
(`RetrievalRun` bzw. `GenerationRun`); dass sie sich verlustfrei zurücklesen
lässt, sichern Tests ab. Ein Auswertungsskript, das die Reihe zurückliest, gibt
es noch nicht.

Läufe mit Reranker werden je Konfiguration dreimal gemacht, berichtet wird die
Spanne statt eines Einzelwerts: Derselbe Reranker-Aufruf kann bei gleicher
Eingabe verschiedene Noten liefern. Auf Eval-Set v3 (`a2454fd`, 20 Kandidaten)
fanden drei Läufe 27, 28 und 28 Belegseiten. Läufe ohne Reranker brauchen seit
[ADR 011](011-vollstaendige-suche-statt-hnsw.md) keine Wiederholung, die
vollständige Suche liefert jedes Mal dasselbe.

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
- `rerank_temperature` gibt es seit `18d1e67`, mit `null` als Default. Ältere
  Läufe mit Reranker haben keine Temperatur gesendet und liefen damit beim
  Standardwert der API, 1.0; ihre Zeilen sagen das nicht. Die Temperatur geht
  über `extra_body` an die API, weil das SDK 1.x den Parameter `temperature`
  entfernt hat; Haiku 4.5 nimmt ihn weiter an.
- Welcher Stand des Eval-Sets gemessen wurde, steht als `eval_set_version` in
  jeder Zeile, gepflegt als `version` in `data/eval_set.yaml`.
