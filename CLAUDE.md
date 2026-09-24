# Arbeitsregeln für Claude Code

Ziel des Projekts ist, die Mechanik eines RAG-Systems durch Eigenbau zu verstehen.
Die Arbeitsteilung ist deshalb Teil des Projekts und keine Vorliebe.

## Grenze

- `src/**` schreibt der Autor selbst. Schreibzugriffe dorthin sind gesperrt, durchgesetzt
  von einem PreToolUse-Hook in `.claude/settings.json`.
- Delegierbar sind `tests/`, `docs/`, Konfiguration, CI und README.

## Fragen zur Kernlogik

In dieser Reihenfolge antworten:

1. Rückfrage zum Kenntnisstand. Erst danach die Erklärung, nie die Lösung vorweg.
2. Das Konzept.
3. Wo es in der Pipeline sitzt: Ingestion, Retrieval, Reranking oder Evaluation.
4. Welcher ADR es bereits einschränkt, mit Nummer (`docs/adr/`).
5. Zeiger auf die maßgebliche API-Dokumentation.
6. Vorschlag für den ersten Test, den der Autor selbst schreibt.

Code höchstens als Signatur, nie als Implementierung. Erklärungen gehören in den Chat;
Docstrings bleiben einzeilig und begründen nur das Nichtoffensichtliche.

## Ausstieg

`delegiere: <Auftrag>` hebt die Grenze für genau diesen Auftrag auf, danach gilt sie
wieder. Mechanisch: Beginnt der Prompt mit `delegiere:`, legt ein UserPromptSubmit-Hook
`.claude/delegate` an, ein Stop-Hook löscht die Datei am Ende der Antwort. Claude legt
die Datei nicht selbst an — sonst sicherte der Hook nichts, was nicht schon die Regel sagt.

## Messaussagen

Jede Zahl zur Retrieval-Qualität nennt ihren Lauf über den Commit-Hash aus
`data/eval_runs.jsonl`, und wo mehrere Läufe derselben Konfiguration vorliegen, die
Spanne statt eines Einzelwerts: Der Reranker ist nicht deterministisch, die HNSW-Suche
approximativ ([ADR 008](docs/adr/008-eval-laeufe-protokollieren.md)).

## Commits

Konventionen stehen in `.claude/commands/commit.md`, aufrufbar als `/commit`.
