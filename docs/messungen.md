# Messungen: Läufe, Streuung und Spannen

Ergänzt den Abschnitt [Ergebnisse](../README.md#ergebnisse) im README.

## Wie gemessen wird

- **Eval-Set** (`data/eval_set.yaml`): 37 Fragen in fünf Kategorien (jeder Lauf stellt alle 37): Nachschlagen (13), Tabelle (8), Zeichnung (7), Zwei Handbücher (Multi-Hop, 4) und Unbeantwortbar (5). Jede Frage nennt die Seiten, die eine korrekte Antwort zitieren muss, und seit v4 erforderliche und ergänzende Fakten: Erforderlich ist, wonach die Frage fragt; ergänzend, was eine richtige Antwort besser macht. Die unbeantwortbaren Fragen prüfen, ob die Generierung ablehnt, statt zu halluzinieren.
- **Zählweise Retrieval:** Gemessen an 36 Belegen aus den 32 beantwortbaren Fragen des Eval-Sets. Die 4 Multi-Hop-Fragen brauchen je zwei; die 5 unbeantwortbaren Fragen haben keinen Beleg und zählen hier nicht mit. Ein Beleg ist eine Handbuchseite. Steht derselbe Inhalt auf zwei Seiten, nennt das Eval-Set beide, und eine davon reicht; gefunden zählt der Beleg dann einmal, auch wenn beide Seiten kommen.
- **Zählweise Antworten:** „Beleg im Prompt zitiert“ setzt die zitierten Belege ins Verhältnis zu denen, die im Prompt lagen. Was die Suche nicht geliefert hat, zählt nicht gegen die Generierung, das zeigt schon die Retrieval-Tabelle. Jeder Beleg zählt einmal, auch wenn mehrere Aussagen ihn zitieren. Ablehnungen zählen getrennt: korrekt bei den 5 unbeantwortbaren Fragen, falsch bei den 32 beantwortbaren.
- **Zählweise Fakten:** Ein prüfendes Modell urteilt je erforderlichem Fakt, ob die Antwort ihn nennt, auslässt oder ihm widerspricht. Vollständig ist eine Antwort, wenn sie alle nennt. Geprüft werden nur Antworten auf beantwortbare Fragen; Ablehnungen zählen schon bei den Antworten oben und hier nicht noch einmal.

## Die Läufe hinter den Zahlen im README

Alle liefen am 2026-10-19 gegen Eval-Set v4, Strategie `naive`, `text-embedding-3-large` mit 1536 Dimensionen, ohne Begrenzung je Dokument, Reranker mit Temperatur 0.0:

| Konfiguration | Läufe | Commit | Datei |
|---|---:|---|---|
| Nur Vektorsuche, `k=5` | 1 | `e85aab9` | `data/retrieval/eval_runs.jsonl` |
| Nur Vektorsuche, `k=50` | 1 | `e85aab9` | `data/retrieval/eval_runs.jsonl` |
| Reranking, `k=5`, 20 Kandidaten, `claude-haiku-4-5-20251001` | 3 | `e85aab9` | `data/retrieval/eval_runs.jsonl` |
| Generierung, Konfiguration wie Reranking, `claude-sonnet-5` | 5 | 3 × `e85aab9`, 2 × `026ce12` | `data/generation/eval_runs.jsonl` |
| Faktenprüfung, `claude-sonnet-5-5`, auf dem Generierungslauf von 12:08 (`026ce12`) | 1 | `ab6e3d5` | `data/facts/eval_runs.jsonl` |

Die Faktenprüfung lief am 2026-10-22 und bewertet die gespeicherten Antworten, ohne sie neu zu erzeugen. Zwei der fünf Generierungsläufe liegen auf `026ce12`, das nur die Läufe davor protokolliert; der Code ist derselbe. Die Vektorsuche ist vollständig und damit reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)), deshalb genügt ohne Reranking ein Lauf. Die Spalte „Unter den 20 Kandidaten“ stammt aus den protokollierten `retrieval_rank`-Werten der Reranking-Läufe und ist in allen dreien gleich.

Auch mit Temperatur 0.0 ist der Reranker nicht deterministisch: Zwischen den drei Läufen wechselt q-035 ihr Ergebnis. Die Läufe auf v3 mit Temperatur 1.0 streuten ebenso um einen Beleg (dort q-007); eine kleinere Streuung durch 0.0 ist damit nicht belegt. In allen drei Läufen verliert der Reranker q-007 und q-014, obwohl ihr Beleg unter den Kandidaten liegt. Die Generierungsläufe ranken ihre Kandidaten selbst neu, deshalb schwankt dort auch, welche Belege im Prompt liegen (25–26 von 36).

Läufe auf früheren Versionen sind mit diesen Zahlen nicht vergleichbar: v4 formuliert viele Fragen aus Sicht eines Anwenders neu, nennt konkrete Typen wie auf dem Typenschild, ersetzt drei Fragen und korrigiert Belegseiten. Nur vier beantwortbare Fragen sind in Text und Belegen gleich geblieben.

## Ein Beispiel: q-035

*Ich bestelle einen Motor DRN132M4 für den Betrieb an einem G120C. Welchen Temperaturfühler sollte ich als Option wählen, damit der Umrichter die Motortemperatur überwacht?* Die Optionen stehen in der Anleitung des SEW-Motors, welche Sensoren der Umrichter auswertet, in der von Siemens:

| Beleg | Was dort steht |
|---|---|
| SEW Motoren-Betriebsanleitung DRN, S. 28 | Optionen /TF (Kaltleiter, PTC), /TH (Bimetallschalter), /PK (Pt1000), /PT (Pt100) |
| SINAMICS G120C Betriebsanleitung, S. 225 | zulässig sind Temperaturschalter (Bimetall), PTC- und KTY84-Sensoren |

| Beleg | Rang in der Vektorsuche | Rang nach Reranking (drei Läufe) |
|---|---:|---:|
| Motoren-Betriebsanleitung, S. 28 | 19 | 5, 5, — |
| G120C Betriebsanleitung, S. 225 | 1 | 1, 1, 2 |

Die Vektorsuche findet die Siemens-Seite sofort, die SEW-Seite nur knapp unter den 20 Kandidaten. Das Reranking holt sie in zwei Läufen auf Platz 5 und damit in den Prompt, im dritten fällt sie heraus. Das ist die Streuung aus dem Abschnitt oben, an einer Frage gezeigt. Was gar nicht unter die Kandidaten kommt, kann das Reranking nicht retten: Unter den Top 20 der Vektorsuche liegen 28 von 36 Belegen, unter den Top 30 sind es 30, unter den Top 50 33, und jeder weitere Kandidat kostet Tokens im Reranking.

## Antworten je Fragetyp

| Fragetyp | Beleg im Prompt zitiert |
|---|---:|
| Zwei Handbücher (Multi-Hop) | 4 / 4 – 5 / 5 |
| Zeichnung | 4 / 5 |
| Nachschlagen | 9 / 10 – 10 / 10 |
| Tabelle | 5 / 6 – 6 / 6 |
| **Gesamt** | **23 / 26 – 25 / 26 (88–96 %)** |

Die Nenner schwanken, weil jeder Lauf neu rerankt und damit andere Belege in den Prompt bringt. Die 5 unbeantwortbaren Fragen lehnt das Modell in allen fünf Läufen ab. Von den 32 beantwortbaren lehnt es in allen fünf Läufen dieselben 4 ab (q-001, q-003, q-028, q-036); bei q-003, q-028 und q-036 lag der Beleg nicht im Prompt, bei q-001 steht die Antwort nur in einer Zeichnung, die die Textextraktion nicht erfasst. In einem Lauf lehnt es zusätzlich q-018 ab, obwohl der Beleg im Prompt lag, mit der Begründung, die Tabelle sei beim Extrahieren durcheinandergeraten.

## Fakten je Fragetyp

| Fragetyp | Antwort vollständig |
|---|---:|
| Zwei Handbücher (Multi-Hop) | 2 / 4 |
| Zeichnung | 3 / 5 |
| Nachschlagen | 11 / 12 |
| Tabelle | 4 / 6 |
| **Gesamt** | **20 / 27 (74 %)** |

Ein Lauf, deshalb Einzelwerte statt Spannen. Geprüft sind 27 Antworten: Im bewerteten Lauf lehnte das Modell neben den 5 unbeantwortbaren Fragen auch q-001, q-003, q-018, q-028 und q-036 ab. Von den 55 erforderlichen Fakten dieser Antworten nennen sie 41, lassen 11 aus und widersprechen 3. Die Widersprüche stehen in zwei Antworten: q-007 gibt die zulässige Ölsumpftemperatur (−15 bis +80 °C) als Umgebungstemperatur aus, q-014 nennt die Querkraftprüfung statt der Bedingung Ma · fB ≤ Ma max.

Alle 55 Urteile sind an den Antworten nachgeprüft und stimmen, auch die 41 „genannt“: Kein Fakt gilt zu Unrecht als genannt. Nicht geprüft werden Aussagen über die erforderlichen Fakten hinaus; eine falsche davon lässt die Antwort vollständig bleiben. Fehlend sind vor allem Angaben, die nur in einer Zeichnung stehen (q-002, Lage der Wärmeklasse auf dem Typenschild), und Bedingungen, die neben der Hauptantwort auf der Seite stehen (q-015 thermische Prüfung, q-025 Derating über +40 °C). Zwei Fakten bündelten Begründung und Nebendetail und ließen dadurch richtige Antworten durchfallen; sie sind seither getrennt (q-012, q-034), die Zahlen oben gelten mit der getrennten Fassung.

Die Prüfung kostet je Lauf 38.591 Input- und 6.775 Output-Tokens, zum Listenpreis von Claude Sonnet 5.5 (2 $ / 10 $ je Mio. Tokens) etwa 0,15 $, bei 2,8 s je Antwort im Median. Wie stark das prüfende Modell zwischen zwei Läufen streut, ist noch nicht gemessen.

## Was das Reranking kostet

| | Nur Vektorsuche | Mit Reranking |
|---|---:|---:|
| Input-Tokens je Frage | — | ~14.700 |
| Output-Tokens je Frage | — | ~250 |
| Kosten je Eval-Lauf (alle 37 Fragen) | < 0,01 $ | ~0,59 $ |
| Latenz je Frage (Median) | 0,2 s | 2,3–2,5 s |

Grundlage sind die je Lauf protokollierten Tokenzahlen (542.543 Input, 9.176–9.178 Output bei 20 Kandidaten, in allen drei Läufen auf `e85aab9`) und der Listenpreis von Claude Haiku 4.5: 1 $ je Mio. Input-, 5 $ je Mio. Output-Tokens. Die Latenz ist der Median über die 37 Fragen, Suche und Reranking zusammen. Die Antwortgenerierung mit Claude Sonnet 5 (2 $ / 10 $ je Mio. Tokens) kommt danach auf 0,61–0,66 $ je Lauf und 4,2–5,4 s je Frage.

Das Reranking ist der teuerste Schritt der Suche: Statt eines Embedding-Aufrufs gehen 20 vollständige Handbuchseiten an ein Sprachmodell. Auf v4 bringt es nur bei Multi-Hop-Fragen etwas (3 / 8 ohne, 4–5 / 8 mit); bei Nachschlage-, Tabellen- und Zeichnungsfragen liegt es gleichauf mit der Vektorsuche. Die Entscheidung könnte künftig je Fragetyp fallen statt pauschal.

## Frühere Läufe

**Eval-Set v3** (Commit `a2454fd`, 2026-10-08, Reranker mit Temperatur 1.0): nur Vektorsuche 22 von 36, unter den 20 Kandidaten 30, mit Reranking 27–28, Top 50 33; Antworten zitierten den Beleg im Prompt in 86–92 %, lehnten 4–5 von 5 unbeantwortbaren Fragen ab und 3 von 31 beantwortbaren fälschlich. Die Läufe stehen in beiden `eval_runs.jsonl`.

**Eval-Set v1:** Der folgende Absatz beschreibt die Zahlen, die bis zu den Läufen auf v3 im README standen (nur Vektorsuche 18–19 von 36, mit Reranking 24–25 von 36). Beide Spalten waren Spannen über wiederholte Läufe mit gleichen Parametern: die Vektorsuche über zwei Läufe (Commits `9db58dc` und `c5c9dfa` in `data/retrieval/eval_runs.jsonl`), das Reranking über drei mit demselben Bewertungsformat (`ee97331`, `95b591c`, `530086d`). Die Läufe liegen auf verschiedenen Commits, deren Änderungen Retrieval und Reranking nicht berührten. Die Streuung der Reranking-Spalte kommt von der Generierung des Rerankers, die nicht deterministisch ist; die 20 Kandidaten davor holt die Vektorsuche nach heutigem Plan der Datenbank ohne Index, also vollständig. Die Spalte „Nur Vektorsuche“ lief über den HNSW-Index von pgvector, der approximativ sucht und bei einzelnen Fragen weniger als fünf Seiten lieferte. Die Suche läuft inzwischen vollständig und ist damit reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)). Die Spannen je Kategorie stammen aus verschiedenen Läufen und summieren sich deshalb nicht direkt auf die Gesamtspanne.

## Wie ein Lauf protokolliert wird

Jeder Lauf hängt eine Zeile an `data/retrieval/eval_runs.jsonl` (Retrieval) beziehungsweise `data/generation/eval_runs.jsonl` (Antworten) und `data/facts/eval_runs.jsonl` (Faktenprüfung) an, mit Konfiguration, Commit-Hash und den Ergebnissen je Frage. Warum und mit welchen Feldern: [ADR 008](adr/008-eval-laeufe-protokollieren.md).
