---
name: test-writer
description: Schreibt Tests nach den Konventionen der bestehenden Suite dieses Repos (Fakes statt echter API-Calls, Factories aus tests/helpers.py, Integrationsmarker, mypy --strict). Nutze diesen Skill, wenn Tests ergänzt, umgebaut oder Lücken in tests/ geschlossen werden sollen, wenn nach der Testabdeckung einer Funktion gefragt wird, oder wenn ein neuer Testfall für einen gefundenen Fehler entstehen soll.
---

# Test-Writer

## Grenze

Schreibt nur in `tests/`. `src/**` ist gesperrt (`CLAUDE.md`). Ist eine Funktion ohne
Änderung in `src/` nicht testbar, wird das benannt, mit einem Vorschlag zur Trennung von
Logik und I/O — aber nicht umgesetzt. Der Umbau ist Arbeit des Autors.

## Konventionen der bestehenden Suite

- **AAA-Struktur**, die drei Abschnitte durch eine Leerzeile getrennt.
- **Testnamen beschreiben Verhalten, nicht Methode:**
  `test_retrieve_per_document_rejects_a_cap_below_one`, nicht `test_retrieve_2`.
- **Keine echten API-Calls.** Die OpenAI- und Anthropic-Clients werden durch Fakes
  ersetzt. Die Bausteine dafür stehen in `tests/helpers.py`, nicht als dupliziertes
  Fixture im Testmodul: Factories für Korpus, PDFs und Eval-Fragen, die fertigen
  Fehlerinstanzen und `NO_CLIENT` für Aufrufe, die den Client nie erreichen dürfen.
  `NO_CLIENT` ist bewusst `None` und kein Mock — ein unerwarteter Zugriff soll die Zeile
  nennen, nicht verschluckt werden.
- **`tests/helpers.py` statt `conftest.py`** für alles, was keine Fixture ist. Ein
  expliziter Import sagt, woher der Helfer kommt.
- **Datenbanktests nur, wo Postgres nötig ist**, markiert mit `@pytest.mark.integration`
  (siehe `tests/test_db.py`, `tests/test_init_db.py`, `tests/test_retrieval.py`). Der
  Marker ist in `pyproject.toml` registriert, `--strict-markers` ist aktiv: ein Tippfehler
  im Dekorator ist ein Fehler, auf der Kommandozeile aber nicht — `-m integraton`
  deselektiert stillschweigend alles.
- **Typannotationen auch in Tests.** `uv run mypy src` deckt `tests/` nicht ab, aber die
  Suite bleibt strikt annotiert. Für Tests sind `D100`, `D103` und `D104` per
  `per-file-ignores` abgeschaltet, Docstrings also nur, wo sie etwas erklären.
- **Nach dem Schreiben:** `uv run pytest` und `uv run ruff check .`.

## `pytest.raises` mit `match=` — offen

Der Bestand hält das nicht durchgehend: 32 `pytest.raises`, davon 23 mit `match=`. Für
**neue** Tests gilt `match=`, damit ein Test nicht auf die falsche Ausnahme desselben Typs
grün läuft. Ob die neun Altfälle nachgezogen werden, hat der Autor nicht entschieden. Bis
dahin wird die Regel nicht als bestehende Konvention des Repos ausgegeben.

## Was ein Test hier belegen soll

Die Entscheidungen der ADRs sind testbar formuliert, und ein Test darf sie festhalten:
kein stiller Rückfall auf die Vektor-Reihenfolge ([ADR 005](../../../docs/adr/005-kein-stiller-rueckfall.md)),
eine Transaktion pro Dokument ([ADR 006](../../../docs/adr/006-transaktion-pro-dokument.md)),
Konfigurationsprüfung vor dem ersten Download ([ADR 007](../../../docs/adr/007-konfiguration-vorab-pruefen.md)).
Ein Test, der eine ADR-Entscheidung absichert, nennt sie im Namen oder im Docstring.
