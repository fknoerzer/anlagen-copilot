---
name: eval-analyst
description: Wertet Läufe aus data/retrieval/eval_runs.jsonl aus: Recall gesamt und je Kategorie, die Differenz zweier Läufe und die Fragen, die gekippt sind. Nutze diesen Skill, wenn nach dem Ergebnis eines Eval-Laufs gefragt wird, zwei Läufe verglichen werden sollen, nach der Streuung zwischen Läufen derselben Konfiguration gefragt wird, oder eine Zahl für die README oder einen ADR belegt werden muss.
---

# Eval-Analyst

Zahlen und Abweichungen, keine Interpretation. Was die Zahlen bedeuten, entscheidet der Autor.

## Eingabe

Ein Lauf oder zwei, benannt über **Commit-Hash** oder **`run_at`**. Niemals über eine
Zeilennummer: Die Zeilen in `data/retrieval/eval_runs.jsonl` tragen keine Nummer, eine Angabe wie
„Lauf 8" ist von außen nicht prüfbar. Ist die Angabe mehrdeutig (derselbe Commit mit
mehreren Läufen), alle Treffer mit ihrem `run_at` auflisten und nachfragen.

## Vorgehen

Aggregation mit dem Interpreter des Projekts, nicht im Kopf:

```bash
uv run python -c "
import json
from collections import defaultdict
runs=[json.loads(l) for l in open('data/retrieval/eval_runs.jsonl',encoding='utf-8')]
for r in runs:
    if r['commit'] not in ('<commit>',): continue
    agg=defaultdict(lambda:[0,0])
    for x in r['results']:
        agg[x['category']][0]+=x['found']; agg[x['category']][1]+=x['expected']
    print(r['commit'], r['run_at'], {k:f'{v[0]}/{v[1]}' for k,v in sorted(agg.items())})
"
```

`recall` steht auch als Feld in der Zeile; es muss zur Summe aus `results` passen. Weicht
es ab, ist das der Befund und der Bericht endet dort.

## Ausgabe

- **Ein Lauf:** Tabelle mit Recall gesamt und je Kategorie, als `gefunden / erwartet` plus
  Prozent. Dazu die Konfiguration: `k`, `per_document`, `candidates`, `reranker`,
  `strategy`, `embedding_model`, `embedding_dimensions`.
- **Zwei Läufe:** zusätzlich die Differenz je Kategorie und die Liste der gekippten
  Fragen mit ihrer `id`, in beide Richtungen (gefunden → nicht gefunden und umgekehrt).
- **Parameterabweichung:** Unterscheiden sich `k`, `candidates`, `per_document`,
  `reranker`, `strategy` oder die Embedding-Felder, wird das vor der Differenz genannt.
  Die Differenz ist dann nicht einer Ursache zuzuordnen, und das gehört dazugesagt.

## Regeln

- Die Kategorie `unanswerable` hat `expected: 0` und zählt nicht in den Recall.
- Eine Differenz unterhalb der Streuung zwischen Läufen derselben Konfiguration ist kein
  Ergebnis. Bekannte Streuung auf Eval-Set v1 bei 20 Kandidaten: 24–25 von 36 Belegseiten
  über drei Läufe (`aab6042`, `4d187b6`, `1f4d839`); nur Vektorsuche mit `k=5`: 18–19 über
  zwei Läufe (`9db58dc`, `6e766d3`). Für v2 gibt es noch keine. Quelle der Streuung ist die
  nicht deterministische Generierung des Rerankers. Die Vektorsuche ist seit
  [ADR 011](../../../docs/adr/011-vollstaendige-suche-statt-hnsw.md) vollständig und
  reproduzierbar; Läufe davor mit `k=5` ohne Reranker liefen über den approximativen
  HNSW-Index und können zu kurze Trefferlisten enthalten.
- Eine Zahl für README oder ADR wird immer mit ihrem Commit-Hash genannt, und wo mehrere
  Läufe derselben Konfiguration vorliegen, als Spanne
  ([ADR 008](../../../docs/adr/008-eval-laeufe-protokollieren.md)).

## Offen

Die Auswertung gehört langfristig in ein Skript unter `scripts/`, dann ist sie testbar,
deterministisch und auch ohne Claude benutzbar. Dieser Skill ist der Übergang; das Skript
schreibt der Autor (`src/` ist gesperrt, siehe `CLAUDE.md`).
