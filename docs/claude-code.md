# Entwicklung mit Claude Code

Die Arbeitsteilung zwischen Autor und [Claude Code](https://claude.com/claude-code) ist nicht nur beschrieben, sondern im Werkzeug verankert.

- **Regeln:** `CLAUDE.md` legt fest, was Claude Code schreiben darf und wie es Fragen zur Kernlogik beantwortet: erst Konzept, Einordnung in Pipeline und ADRs, dann ein Vorschlag für den ersten Test, aber kein Code.
- **Konventionen:** Die Commit-Konventionen liegen als aufrufbarer Befehl in `.claude/commands/`, die Konventionen für Auswertung, Tests und Prompt-Änderungen in `.claude/skills/`.
- **Schreibsperre:** Ein PreToolUse-Hook in `.claude/settings.json` lehnt Schreibzugriffe der Editierwerkzeuge auf `src/**` ab.
- **Freigabe für einen Auftrag:** Beginnt der Prompt des Autors oder eine seiner Zeilen mit `delegiere:`, legt ein weiterer Hook eine Freigabedatei an, die ein Stop-Hook am Ende der Antwort wieder löscht.

Schreibvorgänge über die Shell deckt der Hook nicht ab: Er sichert gegen Abdriften im Alltag, nicht gegen einen entschlossenen Umweg.
