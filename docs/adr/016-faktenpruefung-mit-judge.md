# ADR 016: Faktenprüfung mit einem eigenen Judge-Modell

## Kontext

Die Generierungs-Eval zählt Seiten: ob der Beleg im Prompt lag und ob die
Antwort ihn zitiert. Ob die Aussagen stimmen, misst sie nicht. Eine Antwort kann
die richtige Seite zitieren und den Wert daraus falsch wiedergeben, etwa die
zulässige Ölsumpftemperatur als Umgebungstemperatur (q-007).

## Entscheidung

- Jede Frage im Eval-Set trägt `required_facts`, das, wonach sie fragt, und
  `supplementary_facts`, was eine gute Antwort ergänzen darf. Geprüft werden nur
  die erforderlichen; mit einer einzigen Liste fiele eine kurze richtige Antwort
  durch oder es würde nichts geprüft.
- Ein eigenes Modell (`judge_model`, Claude Sonnet 5.5) urteilt je
  erforderlichem Fakt: `present`, `missing` oder `contradicted`, mit einer
  Begründung vor dem Urteil. Vollständig ist eine Antwort, wenn alle Fakten
  `present` sind.
- Geprüft werden die gespeicherten Antworten eines Generierungslaufs
  (`eval_facts.py`), ohne neu zu generieren. Der Prüflauf nennt den bewerteten
  Lauf über `judged_run_at` und `judged_commit`
  ([ADR 008](008-eval-laeufe-protokollieren.md)).
- Die Urteile werden streng geprüft (`_check_verdicts()`): Fehlt ein Fakt, kommt
  einer doppelt oder einer, der nicht gefragt war, endet der Lauf. Anders als
  beim Reranker gibt es keinen Ersatzwert, weil der Judge das Messinstrument ist
  ([ADR 005](005-kein-stiller-rueckfall.md)).
- Ablehnungen und unbeantwortbare Fragen werden protokolliert, aber nicht
  bewertet.

## Alternativen

- **Der Generator prüft sich selbst.** Gleiches Modell, gleiche blinde Flecken;
  ein eigenes Modell trennt Prüfling und Prüfer.
- **Claude Opus 5.5 als Judge.** Teurer; vorgesehen, falls Sonnet 5.5 an den
  Prüffällen scheitert. Das tat es nicht.
- **Abgleich über Text oder Ähnlichkeit.** Scheitert an Umschreibungen und
  erkennt einen Widerspruch nicht, wenn die Zahl im Text steht, aber zur
  falschen Größe gehört.

## Konsequenzen

- Gemessen auf Eval-Set v4, je drei Läufe: 64–74 % vollständige Antworten bei
  `naive` (`ab6e3d5`, 2 × `7d46dfc`), 61–62 % bei `advanced` (`c4e7435`); rund
  0,15 $ je Lauf.
- Der Judge streut: Bei q-034 nennt er dieselbe Aussage einmal vollständig,
  einmal nicht. Zahlen zu Fakten stehen deshalb als Spanne.
- Die 55 Urteile des ersten Laufs sind von Hand nachgeprüft und stimmen. Zwei
  Fakten, die Begründung und Nebendetail bündelten, sind seither getrennt
  (q-012, q-034).
- Aussagen über die erforderlichen Fakten hinaus prüft der Judge nicht; eine
  falsche Zusatzaussage lässt die Antwort vollständig. Ob die zitierte Seite jede
  Aussage trägt, ist der zweite, noch offene Teil.
