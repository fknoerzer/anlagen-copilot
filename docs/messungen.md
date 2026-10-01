# Messungen: Läufe, Streuung und Spannen

Ergänzt den Abschnitt [Ergebnisse](../README.md#ergebnisse) im README. Alle Zahlen hier wurden wie dort auf Eval-Set v1 gemessen; die Läufe auf v2 liegen vor, ihre Übernahme folgt.

## Woher die Spannen in der Ergebnistabelle stammen

Beide Spalten sind Spannen über wiederholte Läufe mit gleichen Parametern: die Vektorsuche über zwei Läufe (Commits `9db58dc` und `6e766d3` in `data/retrieval/eval_runs.jsonl`), das Reranking über drei mit demselben Bewertungsformat (`aab6042`, `4d187b6`, `1f4d839`). Die Läufe liegen auf verschiedenen Commits, deren Änderungen Retrieval und Reranking nicht berührten. Die Streuung der Reranking-Spalte kommt von der Generierung des Rerankers, die nicht deterministisch ist; die 20 Kandidaten davor holt die Vektorsuche nach heutigem Plan der Datenbank ohne Index, also vollständig. Die Spalte „Nur Vektorsuche“ lief über den HNSW-Index von pgvector, der approximativ sucht und bei einzelnen Fragen weniger als fünf Seiten lieferte. Die Suche läuft inzwischen vollständig und ist damit reproduzierbar ([ADR 011](adr/011-vollstaendige-suche-statt-hnsw.md)). Die Spannen je Kategorie stammen aus verschiedenen Läufen und summieren sich deshalb nicht direkt auf die Gesamtspanne.

## Wie ein Lauf protokolliert wird

Jeder Lauf hängt eine Zeile an `data/retrieval/eval_runs.jsonl` (Retrieval) beziehungsweise `data/generation/eval_runs.jsonl` (Antworten) an, mit Konfiguration, Commit-Hash und den Ergebnissen je Frage. Warum und mit welchen Feldern: [ADR 008](adr/008-eval-laeufe-protokollieren.md).
