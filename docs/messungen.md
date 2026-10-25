# Messungen: Läufe, Streuung und Spannen

Ergänzt den Abschnitt [Ergebnisse](../README.md#ergebnisse) im README.

## Wie gemessen wird

- **Eval-Set** (`data/eval_set.yaml`): 37 Fragen in fünf Kategorien (jeder Lauf stellt alle 37): Nachschlagen (13), Tabelle (8), Zeichnung (7), Zwei Handbücher (Multi-Hop, 4) und Unbeantwortbar (5). Jede Frage nennt die Seiten, die eine korrekte Antwort zitieren muss, und seit v4 erforderliche und ergänzende Fakten: Erforderlich ist, wonach die Frage fragt; ergänzend, was eine richtige Antwort besser macht. Die unbeantwortbaren Fragen prüfen, ob die Generierung ablehnt, statt zu halluzinieren.
- **Zählweise Retrieval:** Gemessen an 36 Belegen aus den 32 beantwortbaren Fragen des Eval-Sets. Die 4 Multi-Hop-Fragen brauchen je zwei; die 5 unbeantwortbaren Fragen haben keinen Beleg und zählen hier nicht mit. Ein Beleg ist eine Handbuchseite. Steht derselbe Inhalt auf zwei Seiten, nennt das Eval-Set beide, und eine davon reicht; gefunden zählt der Beleg dann einmal, auch wenn beide Seiten kommen.
- **Zählweise Antworten:** „Beleg im Prompt zitiert“ setzt die zitierten Belege ins Verhältnis zu denen, die im Prompt lagen. Was die Suche nicht geliefert hat, zählt nicht gegen die Generierung, das zeigt schon die Retrieval-Tabelle. Jeder Beleg zählt einmal, auch wenn mehrere Aussagen ihn zitieren. Ablehnungen zählen getrennt: korrekt bei den 5 unbeantwortbaren Fragen, falsch bei den 32 beantwortbaren.
- **Zählweise Fakten:** Ein prüfendes Modell urteilt je erforderlichem Fakt, ob die Antwort ihn nennt, auslässt oder ihm widerspricht. Vollständig ist eine Antwort, wenn sie alle nennt. Geprüft werden nur Antworten auf beantwortbare Fragen; Ablehnungen zählen schon bei den Antworten oben und hier nicht noch einmal.

## Die Läufe hinter den Zahlen im README

Alle gegen Eval-Set v4, `text-embedding-3-large` mit 1536 Dimensionen, ohne Begrenzung je Dokument, Reranker `claude-haiku-4-5-20251001` mit Temperatur 0.0 und 20 Kandidaten, Generierung `claude-sonnet-5`, Faktenprüfung `claude-sonnet-5-5`:

| Konfiguration | `naive` | `advanced` (Docling) |
|---|---|---|
| Nur Vektorsuche, `k=5` und `k=50` | je 1 × `e85aab9` | je 1 × `e2a86c3` |
| Reranking, `k=5` | 3 × `e85aab9` | 3 × `c4e7435` |
| Generierung | 3 × `e85aab9`, 2 × `026ce12` | 3 × `c4e7435` |
| Faktenprüfung | 3: `ab6e3d5`, 2 × `7d46dfc` | 3 × `c4e7435` |

Dateien: `data/{retrieval,generation,facts}/eval_runs.jsonl`. `026ce12` und `7d46dfc` protokollieren nur Läufe, der Code ist derselbe. Die Faktenprüfung bewertet die gespeicherten Antworten, bei `naive` die Läufe von 12:00, 12:02 und 12:08. Die Vektorsuche ist vollständig und reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)), deshalb genügt ohne Reranking ein Lauf.

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

Antworten, die alle erforderlichen Fakten nennen, je drei Läufe:

| Fragetyp | `naive` | `advanced` |
|---|---:|---:|
| Zwei Handbücher (Multi-Hop) | 1–2 / 4 | 0 / 3–4 |
| Zeichnung | 2–3 / 5 | 2–3 / 6 |
| Nachschlagen | 10–11 / 12 | 11 / 12 |
| Tabelle | 4 / 6–7 | 4 / 7 |
| **Gesamt** | **64–74 %** | **61–62 %** |

Die Nenner schwanken mit den Ablehnungen. Die Spanne bei `naive` (18 bis 20 Antworten) ist Streuung von Generierung und Judge zusammen: Bei q-034 nennt der Judge dieselbe Aussage einmal vollständig, einmal nicht. Die 55 Urteile des ersten Laufs sind von Hand nachgeprüft und stimmen; Aussagen über die erforderlichen Fakten hinaus prüft der Judge nicht.

Durchgehend widersprochen: q-007 gibt die Ölsumpftemperatur (−15 bis +80 °C) als Umgebungstemperatur aus, q-014 nennt die Querkraftprüfung statt Ma · fB ≤ Ma max. Häufig fehlend: Angaben nur in einer Zeichnung (q-002) und Bedingungen neben der Hauptantwort (q-015, q-025). Je Lauf rund 0,15 $ und 2,8 s je Antwort.

## `advanced` gegen `naive`

| | `naive` | `advanced` |
|---|---:|---:|
| Vektorsuche, Top 5 | 24 / 36 | 22 / 36 |
| Reranking, Top 5 | 25–26 / 36 | 27 / 36 |
| Beleg im Prompt zitiert | 23–25 | 23–25 |
| Falsche Ablehnungen | 4–5 / 32 | 3–4 / 32 |
| Antworten mit allen Fakten | 64–74 % | 61–62 % |
| Input-Tokens Reranking / Generierung je Lauf | 543 k / 205 k | 629 k / 226 k |

Docling hilft dem Reranking, vor allem bei Multi-Hop (6 statt 4–5 von 8), aber noch nicht den Antworten. Der deutlichste Verlust ist q-035: SEW-Motoren S. 28 besteht unter Docling aus kleinen Tabellen mit gleichen Kopfzeilen, fällt aus den Top 50 der Vektorsuche, und der Antwort fehlen die Optionen /TH, /PK und /PT. q-037 (OPC UA) zählt unter `advanced` als beantwortet, sagt aber in allen drei Läufen, dass die Unterlagen OPC UA nicht nennen. Hintergrund: [ADR 015](adr/015-docling-fuer-advanced.md).

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
