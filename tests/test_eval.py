from pathlib import Path

import pytest
import yaml

from anlagen_copilot.eval import EvalSet, load_eval


def _make_eval_set() -> EvalSet:
    """Baut ein minimal gültiges EvalSet, Pflichtfelder mit Platzhaltern.

    Tests, die nur ein einzelnes Feld prüfen, müssen so nicht bei jedem
    Aufruf alle Pflichtfelder von EvalQuestion ausschreiben.
    """
    defaults: dict[str, object] = {
        "questions": [
            {
                "id": "q-test",
                "category": "lookup",
                "question": "Testfrage?",
                "expected_sources": [
                    {"document_id": "sew-getriebe-ba", "page": 1},
                ],
                "expected_facts": ["Testfakt."],
                "notes": "Test-Notiz.",
            },
        ],
    }
    return EvalSet.model_validate(defaults)


def test_load_eval_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources:
      - document_id: sew-getriebe-ba
        page: 1
    expected_facts:
      - Testfakt.
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    eval_set = load_eval(f)

    assert len(eval_set.questions) == 1
    assert eval_set.questions[0].category == "lookup"


def test_real_eval_yaml_is_valid() -> None:
    """Regressionscheck: data/eval_set.yaml bleibt gegen das Schema valide.

    Bewusst ohne harte Fragenanzahl, da das Set wachsen soll — prüft nur
    strukturelle Invarianten, die bei jeder Set-Größe gelten müssen.
    """
    eval_set = load_eval()

    ids = [question.id for question in eval_set.questions]
    assert len(ids) > 0
    assert len(ids) == len(set(ids))


def test_load_eval_rejects_broken_yaml(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text("documents: [{id: a\n", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        load_eval(f)


def test_load_eval_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_eval(tmp_path / "gibtsnicht.yaml")


def test_load_eval_fails_with_missing_content(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources: []
    expected_facts: []
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Frage braucht Quellen und Fakten"):
        load_eval(f)


def test_load_eval_succeeds_with_unanswerable_question(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: unanswerable
    question: Testfrage?
    expected_sources: []
    expected_facts: []
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )

    eval_set = load_eval(f)

    assert len(eval_set.questions) == 1
    assert eval_set.questions[0].category == "unanswerable"


def test_load_eval_fails_with_incorrect_unanswerable_question(tmp_path: Path) -> None:
    """Nutzt bewusst eine echte document_id, um gezielt nur
    check_unanswerable_consistency zu treffen, statt versehentlich
    check_document_id auszulösen (siehe
    test_load_eval_fails_with_incorrect_source_document_id für den anderen Fall).
    """
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: unanswerable
    question: Testfrage?
    expected_sources: 
          - document_id: sew-getriebe-ba
            page: 1
    expected_facts: []
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="darf keine Quellen/Fakten"):
        load_eval(f)


def test_load_eval_fails_with_incorrect_source_document_id(tmp_path: Path) -> None:
    """Läuft bewusst gegen das echte corpus.yaml statt gemockt.

    corpus.yaml ist eine statische, versionierte Datei (kein Netzwerk, kein
    instabiler Zustand) — Mocking von load_corpus würde hier nur Komplexität
    ohne echten Isolationsgewinn hinzufügen.
    """
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources:
      - document_id: falsche-id
        page: 1
    expected_facts:
      - x
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="nicht in corpus.yaml gefunden"):
        load_eval(f)
