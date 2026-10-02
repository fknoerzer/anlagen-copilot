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

Code höchstens als Signatur, nie als Implementierung. Erklärungen gehören in den Chat.

## Docstrings

- Die erste Zeile sagt in einfachen Worten, was die Funktion tut.
- In `src/` darf danach je ein Absatz eine nicht offensichtliche Entscheidung mit
  ihrer Folge begründen, dazu `Raises:`, wenn etwas scheitern kann. Vorbild:
  `extract_pages()` in `ingest.py`.
- Einzeilig bleiben Tests und Pydantic-Modelle, deren Schema ans Modell geht: Ihr
  Docstring wird zur `description` im Schema und bei jedem Aufruf mitgelesen.

## Ausstieg

`delegiere: <Auftrag>` hebt die Grenze für genau diesen Auftrag auf, danach gilt sie
wieder. Mechanisch: Beginnt der Prompt oder eine seiner Zeilen mit `delegiere:` (die
IDE-Erweiterung stellt dem Prompt Kontext voran), legt ein UserPromptSubmit-Hook
`.claude/delegate` an, ein Stop-Hook löscht die Datei am Ende der Antwort. Claude legt
die Datei nicht selbst an — sonst sicherte der Hook nichts, was nicht schon die Regel sagt.

Nach jedem Auftrag, bei dem Claude Dateien ändert, ob über `delegiere:` in `src/` oder
in den delegierbaren Bereichen, zeigt die Antwort genau, was geändert wurde und warum,
damit der Autor den Code versteht, den er nicht selbst geschrieben hat:

- Je geänderter Datei die Änderung selbst: bei Code in `src/` der neue oder geänderte
  Abschnitt als Codeblock, bei kleinen Änderungen vorher und nachher.
- Zu jeder Änderung der Grund in ein, zwei Sätzen: welches Problem sie löst oder
  welche Entscheidung sie umsetzt.
- Was über den Auftrag hinaus angefasst wurde, ausdrücklich als solches benannt.
- Wie geprüft wurde (Tests, mypy, Ruff, ein Probeaufruf) und was offen bleibt.

## Messaussagen

Jede Zahl zur Retrieval-Qualität nennt ihren Lauf über den Commit-Hash aus
`data/retrieval/eval_runs.jsonl`, und wo mehrere Läufe derselben Konfiguration
vorliegen, die Spanne statt eines Einzelwerts: Der Reranker ist nicht deterministisch
([ADR 008](docs/adr/008-eval-laeufe-protokollieren.md)). Die Vektorsuche ist seit
[ADR 011](docs/adr/011-vollstaendige-suche-statt-hnsw.md) vollständig und damit
reproduzierbar; ältere Läufe mit `k=5` ohne Reranker liefen über den approximativen
HNSW-Index.

## Commits

Konventionen stehen in `.claude/commands/commit.md`, aufrufbar als `/commit`.
