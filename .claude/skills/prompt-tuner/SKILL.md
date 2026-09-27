---
name: prompt-tuner
description: Verändert den Reranker-Prompt in kontrollierten Durchgängen und misst die Wirkung gegen das Eval-Set, mit Blick auf Streuung, Tokens und Kosten. Nutze diesen Skill, wenn der Prompt in src/anlagen_copilot/rerank.py verbessert werden soll, eine Prompt-Variante bewertet werden soll, oder gefragt wird, ob eine Änderung am Reranking etwas gebracht hat.
---

# Prompt-Tuner

## Voraussetzung, sonst kein Lauf

**Die Variante muss protokollierbar sein.** `RetrievalRun` in `src/anlagen_copilot/scripts/eval_retrieval.py` hat
kein Feld für die Prompt-Variante. Ohne ein solches Feld — etwa ein Hash des System-Prompts
— ist ein Lauf nachträglich nicht der Variante zuzuordnen, und die Messreihe wird
wertlos. Das Feld ergänzt der Autor (`src/` ist gesperrt); vorher wird kein Lauf gestartet.
Derselbe offene Punkt wie `eval_set_version` in
[ADR 008](../../../docs/adr/008-eval-laeufe-protokollieren.md).

**Latenz wird nicht protokolliert.** Die Laufdatensätze halten nur Tokenzahlen. Solange das
so ist, wird über Tokens und Kosten berichtet und über Latenz nichts behauptet.

## Was sich ändern lässt

Der System-Prompt und der Kandidaten-Prompt stehen in `src/anlagen_copilot/rerank.py`
(`_SYSTEM_PROMPT`, `_build_prompt()`). Kandidaten für eine Variante: die Notenskala 0–3,
die Formulierung der Stufen, die Reihenfolge der Kandidaten im Prompt, die Länge der
Seitenauszüge. Das Ausgabeformat gehört nicht dazu — das ist mit
[ADR 004](../../../docs/adr/004-reranker-ausgabe.md) entschieden und gemessen.

## Ablauf

1. Aktuellen Prompt auslesen und die zu ändernde Variante benennen: eine Änderung pro
   Durchgang, nie zwei.
2. Variante als Text vorschlagen. Geändert wird `rerank.py` erst nach `delegiere:`
   (`CLAUDE.md`).
3. Eval-Lauf mit sonst unveränderten Parametern:
   `uv run python -m anlagen_copilot.scripts.eval_retrieval --k 5 --candidates 20 --reranker claude-haiku-4-5`
4. Wiederholen, bis die Variante über der Streuung liegt (siehe Rechnung unten).
5. Auswerten mit dem Skill `eval-analyst`, **je Kategorie**, nicht über den Gesamtwert:
   Multi-Hop und Tabelle verhalten sich gegenläufig zum Mittel.
6. Ergebnis protokollieren. Bei einer Verbesserung eine Notiz für einen ADR, mit den
   Commit-Hashes der Läufe.

## Die Rechnung, die vor dem ersten Lauf steht

- Ein Lauf kostet rund 0,62 $: 560.094 Input- und 11.620 Output-Tokens bei 20 Kandidaten,
  Claude Haiku 4.5 zu 1 $ je Mio. Input- und 5 $ je Mio. Output-Tokens.
- Die bekannte Streuung derselben Konfiguration ist 24–25 von 36 Belegseiten. Eine Variante
  muss also **mindestens drei Belegseiten** bewegen, um überhaupt aus dem Rauschen zu
  kommen, und braucht **drei Läufe** (rund 1,90 $), damit die Aussage trägt.
- Ein Durchgang mit einem Lauf und einem Zugewinn von einer Seite ist kein Ergebnis. Das
  wird so gesagt und nicht als Verbesserung berichtet.
- Eine Variante, die zwei Prozentpunkte bringt und die Tokens verdoppelt, ist keine
  Verbesserung. Tokens gehören in jeden Bericht.
