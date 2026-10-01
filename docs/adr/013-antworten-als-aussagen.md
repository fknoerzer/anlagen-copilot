# ADR 013: Antworten als Aussagen mit Seiten-IDs

## Kontext

Die Generierung soll jede Aussage auf eine Handbuchseite zurückführen. Eine
Zitatmarke wie `[2]` im Fließtext ist dafür der naheliegende Weg, hat in diesem
Korpus aber zwei Schwächen:

- Die Zitate müssen mit einem Suchmuster aus dem Text gelesen werden. In den
  Handbüchern stehen Einheiten ebenfalls in eckigen Klammern (`[1/min]`, `[Nm]`,
  `[°C]`); übernimmt das Modell einen Tabellenkopf, liest das Suchmuster ihn als
  Zitat oder muss ihn eigens ausschließen.
- Abweichende Schreibweisen wie `[1, 3]` oder `[1-3]` werden entweder übersehen,
  dann geht ein Zitat still verloren, oder müssen zusätzlich geparst werden.

Ob das Modell antwortet oder ablehnt, muss außerdem als Zustand vorliegen, nicht
als Satz, der erst erkannt werden muss. Eine Schwelle auf dem Score der
Vektorsuche taugt dafür nicht, weil Treffer und unbeantwortbare Fragen
überlappen. Im Lauf `3b25613` (v2, nur Vektorsuche) erreicht die beste
unbeantwortbare Frage einen Score von 0,663, der schwächste Treffer nur 0,461.

## Entscheidung

Die Antwort kommt als strukturierte Ausgabe ([ADR 012](012-strukturierte-ausgabe.md))
im Modell `GeneratedAnswer`: ein Feld `answered` und eine Liste `statements`.
Jede Aussage ist ein Satz oder ein Arbeitsschritt und trägt in `sources` die IDs
der Seiten, aus denen sie stammt. Die IDs zählen ab 1 in der Reihenfolge, in der
die Seiten im Prompt stehen; Seitenzahlen und Dokumentnamen stehen nicht im
Text.

Geprüft wird an zwei Stellen, beides laut ([ADR 005](005-kein-stiller-rueckfall.md)):

- Ein Validator in `GeneratedAnswer`: Eine Ablehnung (`answered: false`)
  zitiert keine Seite, eine Antwort zitiert mindestens eine.
- `_check_ids()` in `generate()`: jede ID liegt zwischen 1 und der Zahl der
  übergebenen Seiten. Das Schema kann das nicht leisten, weil strukturierte
  Ausgabe kein `minimum` und `maximum` erlaubt und die Seitenzahl nicht kennt.

Eine Aussage, die eine Lücke benennt („Zu X enthalten die Seiten nichts“), hat
leere `sources`. Ebenso alle Aussagen einer Ablehnung.

## Alternativen

- **Zitatmarken `[n]` im Text.** Siehe Kontext: Suchmuster, Verwechslung mit
  Einheiten, still verlorene Zitate.
- **Text mit Marken und zusätzlich eine Liste zitierter IDs.** Zwei Quellen für
  dieselbe Information, die sich widersprechen können: `[3]` im Text, `2` in der
  Liste.
- **Eine Liste zitierter IDs ohne Marken im Text.** Eindeutig, aber ohne
  Zuordnung von Aussage zu Seite. Weder die Oberfläche noch die Evaluation
  könnten dann sagen, welcher Satz woher stammt.
- **Das Citations-Feature der API.** Liefert die wörtlich zitierte Stelle je
  Aussage, lässt sich aber nicht mit strukturierter Ausgabe kombinieren, und
  `answered` müsste anders entstehen.

## Konsequenzen

- Die Antwort-Evaluation zählt Seiten, nicht Zitate: Sie bildet erwartete,
  übergebene und zitierte Seiten als Mengen und vergleicht sie
  (`scripts/eval_generate.py`).
- Die Oberfläche setzt die Zitatmarken beim Anzeigen selbst. Ob eine Antwort aus
  Arbeitsschritten oder aus Sätzen besteht, ist im Format nicht unterschieden.
- Die Regel „Aussagen einer Ablehnung zitieren nichts“ kollidiert mit „jede
  Sachaussage braucht einen Beleg“, wenn das Modell eine Ablehnung begründen
  will. In Probeläufen, die nicht protokolliert sind, fügte es zu q-004 trotz
  Anweisung einen unbelegten Fakt hinzu. Wie oft das vorkommt, zeigen erst die
  Läufe der Antwort-Evaluation.
- Die gespeicherten Aussagen samt Seiten erlauben eine spätere Faktenprüfung
  auf genau diesen Antworten, ohne neu zu generieren.
