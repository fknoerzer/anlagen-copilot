# ADR 017: Die API antwortet, wie gemessen wurde

## Kontext

`POST /api/ask` beantwortet Fragen für eine Oberfläche. Die Zahlen in README und
`messungen.md` gelten nur für sie, wenn die API dieselbe Pipeline mit derselben
Konfiguration ausführt wie die Generierungs-Eval.

## Entscheidung

- Suche und Generierung werden an genau einer Stelle verbunden,
  `answer_question()` in `pipeline.py`. Eval (`run_generation()`) und API
  (`answer()`) rufen beide diese Funktion auf.
- Die Konfiguration kommt aus den Settings `ask_*`, deren Defaults die der
  gemessenen Läufe sind. Je Anfrage wählbar ist nur die Strategie; `ask_strategy`
  ist von `ingest_strategy` getrennt, damit ein Neu-Ingest nicht ändert, was
  die API durchsucht.
- Die Antwort enthält nur, was der Aufrufer für diese Frage braucht:
  `answered`, `statements`, `citations`. Zeiten und Tokens gehen ins Log.
- `citations` enthält jede Seite im Prompt, zitiert oder nicht, und `n` ist ihre
  Position dort. Aussage `[n]` ist damit immer `citations[n-1]`.

## Alternativen

- **Eval und API verbinden die Schritte je für sich.** Zwei einfache Stellen,
  aber eine Änderung an nur einer lässt die API anders antworten als gemessen,
  ohne dass ein Test es merkt.
- **Die ganze Konfiguration je Anfrage.** Bequem für Experimente, aber dann gilt
  keine Messung mehr für das, was ausgeliefert wird.
- **Zeiten, Tokens und Konfiguration in jeder Antwort.** Drei Modelle mehr, die
  nur der Entwickler braucht; die Konfiguration ist für jede Frage gleich.

## Konsequenzen

- API und Oberfläche binden an `127.0.0.1`: jede Anfrage kostet Tokens, und es
  gibt keine Anmeldung. Ein öffentlicher Betrieb bräuchte beides plus eine
  Kostengrenze.
- Der Default `ask_strategy=advanced` setzt den Docling-Index voraus
  ([ADR 015](015-docling-fuer-advanced.md)); ohne ihn findet die Suche nichts.
- Fehler werden noch nicht auf HTTP-Codes abgebildet: Fehlt die Datenbank oder
  ein Index, antwortet die API mit 500.
