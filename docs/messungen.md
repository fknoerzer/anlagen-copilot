# Messungen: Läufe, Streuung und Spannen

Ergänzt den Abschnitt [Ergebnisse](../README.md#ergebnisse) im README.

## Wie gemessen wird

- **Eval-Set** (`data/eval_set.yaml`): 36 Fragen in fünf Kategorien (jeder Lauf stellt alle 36): Nachschlagen (10), Tabelle (8), Zeichnung (8), Zwei Handbücher (Multi-Hop, 5) und Unbeantwortbar (5). Jede Frage nennt die Seiten, die eine korrekte Antwort zitieren muss, und Fakten, die in einer Antwort stehen sollten; eine Trennung in erforderliche und ergänzende Fakten ist geplant. Die unbeantwortbaren Fragen prüfen, ob die Generierung ablehnt, statt zu halluzinieren.
- **Zählweise Retrieval:** Gemessen an 36 Belegen aus den 31 beantwortbaren Fragen des Eval-Sets. Die 5 Multi-Hop-Fragen brauchen je zwei; die 5 unbeantwortbaren Fragen haben keinen Beleg und zählen hier nicht mit. Ein Beleg ist eine Handbuchseite. Steht derselbe Inhalt in zwei Handbüchern, nennt das Eval-Set seit v3 beide Seiten, und eine davon reicht; gefunden zählt der Beleg dann einmal, auch wenn beide Seiten kommen.
- **Zählweise Antworten:** „Beleg im Prompt zitiert“ setzt die zitierten Belege ins Verhältnis zu denen, die im Prompt lagen. Was die Suche nicht geliefert hat, zählt nicht gegen die Generierung, das zeigt schon die Retrieval-Tabelle. Jeder Beleg zählt einmal, auch wenn mehrere Aussagen ihn zitieren. Ablehnungen zählen getrennt: korrekt bei den 5 unbeantwortbaren Fragen, falsch bei den 31 beantwortbaren.

## Die Läufe hinter den Zahlen im README

Alle liefen am 2026-10-08 auf Commit `a2454fd` gegen Eval-Set v3, Strategie `naive`, `text-embedding-3-large` mit 1536 Dimensionen, ohne Begrenzung je Dokument:

| Konfiguration | Läufe | Datei |
|---|---:|---|
| Nur Vektorsuche, `k=5` | 1 | `data/retrieval/eval_runs.jsonl` |
| Nur Vektorsuche, `k=50` | 1 | `data/retrieval/eval_runs.jsonl` |
| Reranking, `k=5`, 20 Kandidaten, `claude-haiku-4-5-20251001` | 3 | `data/retrieval/eval_runs.jsonl` |
| Generierung, Konfiguration wie Reranking, `claude-sonnet-5` | 3 | `data/generation/eval_runs.jsonl` |

Die Vektorsuche ist vollständig und damit reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)), deshalb genügt ohne Reranking ein Lauf. Die Spalte „Unter den 20 Kandidaten“ stammt aus den protokollierten `retrieval_rank`-Werten der drei Reranking-Läufe und ist in allen dreien gleich. Die Streuung der Reranking-Spalte kommt von der Bewertung des Rerankers, die nicht deterministisch ist; zwischen den drei Läufen wechselt nur q-007 ihr Ergebnis. Die Generierungsläufe ranken ihre Kandidaten selbst neu, deshalb schwankt dort auch, welche Belege im Prompt liegen (25–28 von 36).

Läufe auf v1 und v2 sind mit diesen Zahlen nicht vergleichbar: v3 korrigiert sechs Belegseiten und lässt bei q-007 gleichwertige Seiten in zwei Handbüchern gelten.

## Ein Beispiel: q-008

*Der Umrichter meldet die Störung F07011 "Motor Übertemperatur". Welche Reaktion löst das am Umrichter aus, und was sollte laut der Motor-Betriebsanleitung zusätzlich geprüft werden, wenn sich der Motor zu stark erwärmt?* Die Störmeldung kommt vom Siemens-Umrichter, die Prüfschritte stehen in der Anleitung des SEW-Motors:

| Beleg | Was dort steht |
|---|---|
| SINAMICS G120C Listenhandbuch, S. 501 | F07011 löst die Reaktion AUS2 aus; Ursachen: Überlastung, zu hohe Umgebungstemperatur, Sensorfehler |
| SEW Motoren-Betriebsanleitung DRN, S. 261 | „Motor erwärmt sich zu stark": Kühlluft, Luftfilter und Umgebungstemperatur prüfen, ggf. Fremdlüfter nachrüsten |

| Beleg | Rang in der Vektorsuche | Rang nach Reranking (drei Läufe) |
|---|---:|---:|
| Listenhandbuch, S. 501 | 17 | 2–4 |
| Motoren-Betriebsanleitung, S. 261 | nicht unter den Top 50 | — |

Aus 20 Kandidaten holt das Reranking die eine Seite nach vorne, die dort überhaupt vorkommt; die zweite findet die Vektorsuche nicht. Das verbleibende Problem ist also nicht mehr die Reihenfolge innerhalb der Kandidaten, sondern was gar nicht erst hineinkommt. Mehr Kandidaten helfen nur begrenzt: Unter den Top 30 der Vektorsuche liegt kein Beleg mehr als unter den Top 20, unter den Top 50 sind es 33 von 36, und jeder weitere Kandidat kostet Tokens im Reranking.

## Antworten je Fragetyp

| Fragetyp | Beleg im Prompt zitiert |
|---|---:|
| Zwei Handbücher (Multi-Hop) | 3 / 3 – 5 / 6 |
| Zeichnung | 6 / 7 |
| Nachschlagen | 7 / 8 |
| Tabelle | 6 / 7 – 7 / 7 |
| **Gesamt** | **23 / 25 – 25 / 28 (86–92 %)** |

Die Nenner schwanken, weil jeder Lauf neu rerankt und damit andere Belege in den Prompt bringt. Von den 5 unbeantwortbaren Fragen lehnt das Modell 4–5 ab; die eine, die es in zwei Läufen beantwortet, ist q-022. Von den 31 beantwortbaren lehnt es in allen drei Läufen dieselben 3 ab, bei zweien davon lag der Beleg nicht im Prompt.

## Was das Reranking kostet

| | Nur Vektorsuche | Mit Reranking |
|---|---:|---:|
| Input-Tokens je Frage | — | ~15.300 |
| Output-Tokens je Frage | — | ~250 |
| Kosten je Eval-Lauf (alle 36 Fragen) | < 0,01 $ | ~0,60 $ |
| Latenz je Frage (Median) | 0,2 s | 2,8–3,0 s |

Grundlage sind die je Lauf protokollierten Tokenzahlen (550.392 Input, 8.928 Output bei 20 Kandidaten, in allen drei Läufen auf `a2454fd`) und der Listenpreis von Claude Haiku 4.5: 1 $ je Mio. Input-, 5 $ je Mio. Output-Tokens. Die Latenz ist der Median über die 36 Fragen, für das Reranking 2,6–2,7 s plus 0,2–0,3 s Suche. Die Antwortgenerierung mit Claude Sonnet 5 kommt danach auf ~0,58 $ je Lauf und 3,3–3,8 s je Frage.

Das Reranking ist der teuerste Schritt der Suche: Statt eines Embedding-Aufrufs gehen 20 vollständige Handbuchseiten an ein Sprachmodell. Bei Nachschlagefragen, die schon ohne Reranking bei 70 % liegen, steht dieser Aufwand in einem schlechteren Verhältnis zum Ertrag als bei Multi-Hop-Fragen. Die Entscheidung könnte künftig je Fragetyp fallen statt pauschal.

## Frühere Läufe auf Eval-Set v1

Der folgende Abschnitt beschreibt die Zahlen, die bis zu den Läufen auf v3 im README standen (nur Vektorsuche 18–19 von 36, mit Reranking 24–25 von 36). Beide Spalten waren Spannen über wiederholte Läufe mit gleichen Parametern: die Vektorsuche über zwei Läufe (Commits `9db58dc` und `c5c9dfa` in `data/retrieval/eval_runs.jsonl`), das Reranking über drei mit demselben Bewertungsformat (`ee97331`, `95b591c`, `530086d`). Die Läufe liegen auf verschiedenen Commits, deren Änderungen Retrieval und Reranking nicht berührten. Die Streuung der Reranking-Spalte kommt von der Generierung des Rerankers, die nicht deterministisch ist; die 20 Kandidaten davor holt die Vektorsuche nach heutigem Plan der Datenbank ohne Index, also vollständig. Die Spalte „Nur Vektorsuche“ lief über den HNSW-Index von pgvector, der approximativ sucht und bei einzelnen Fragen weniger als fünf Seiten lieferte. Die Suche läuft inzwischen vollständig und ist damit reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)). Die Spannen je Kategorie stammen aus verschiedenen Läufen und summieren sich deshalb nicht direkt auf die Gesamtspanne.

## Wie ein Lauf protokolliert wird

Jeder Lauf hängt eine Zeile an `data/retrieval/eval_runs.jsonl` (Retrieval) beziehungsweise `data/generation/eval_runs.jsonl` (Antworten) an, mit Konfiguration, Commit-Hash und den Ergebnissen je Frage. Warum und mit welchen Feldern: [ADR 008](adr/008-eval-laeufe-protokollieren.md).
