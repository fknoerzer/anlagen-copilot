from pathlib import Path

import pytest
import yaml

from anlagen_copilot.eval import load_eval


def test_load_eval_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v1
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources:
      - any_of_pages:
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
    """Regression check: data/eval_set.yaml stays valid against the schema.

    Deliberately without a hard question count, since the set is meant to grow
    — checks only structural invariants that must hold at any set size.
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
        load_eval(tmp_path / "does-not-exist.yaml")


def test_load_eval_fails_with_missing_content(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v1
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
    with pytest.raises(ValueError, match="answerable question needs sources and facts"):
        load_eval(f)


def test_load_eval_succeeds_with_unanswerable_question(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v1
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
    """Reject an unanswerable question that carries sources.

    The document_id is a real one on purpose, so `check_unanswerable_consistency`
    is what fails rather than `check_document_id` tripping first — that other
    case is `test_load_eval_fails_with_incorrect_source_document_id`.
    """
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v1
questions:
  - id: q-test
    category: unanswerable
    question: Testfrage?
    expected_sources:
      - any_of_pages:
          - document_id: sew-getriebe-ba
            page: 1
    expected_facts: []
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not have sources or facts"):
        load_eval(f)


def test_load_eval_fails_with_incorrect_source_document_id(tmp_path: Path) -> None:
    """Runs against the real corpus.yaml on purpose, rather than a mock.

    corpus.yaml is a static, version-controlled file — no network, no unstable
    state. Mocking load_corpus here would only add complexity without buying
    any real isolation.
    """
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v1
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources:
      - any_of_pages:
          - document_id: falsche-id
            page: 1
    expected_facts:
      - x
    notes: Test-Notiz.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not found in corpus.yaml"):
        load_eval(f)


def test_load_eval_reads_the_version(tmp_path: Path) -> None:
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v7
questions:
  - id: q-test
    category: unanswerable
    question: Testfrage?
    expected_sources: []
    expected_facts: []
""",
        encoding="utf-8",
    )

    eval_set = load_eval(f)

    assert eval_set.version == "v7"


def test_load_eval_rejects_a_set_without_version(tmp_path: Path) -> None:
    """A set without a version must not pass as v1 — only old runs get that default."""
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
questions:
  - id: q-test
    category: unanswerable
    question: Testfrage?
    expected_sources: []
    expected_facts: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="version"):
        load_eval(f)


def test_load_eval_rejects_a_source_without_pages(tmp_path: Path) -> None:
    """An empty source could never be found and would count as a miss in every run."""
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v-test
questions:
  - id: q-test
    category: lookup
    question: Testfrage?
    expected_sources:
      - any_of_pages: []
    expected_facts:
      - Testfakt.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="any_of_pages"):
        load_eval(f)


def test_load_eval_rejects_a_page_in_two_sources(tmp_path: Path) -> None:
    """One hit on a shared page would count both sources as found."""
    f = tmp_path / "eval_set.yaml"
    f.write_text(
        """
version: v-test
questions:
  - id: q-test
    category: multi-hop
    question: Testfrage?
    expected_sources:
      - any_of_pages:
          - document_id: sew-getriebe-ba
            page: 1
      - any_of_pages:
          - document_id: sew-getriebe-ba
            page: 2
          - document_id: sew-getriebe-ba
            page: 1
    expected_facts:
      - Testfakt.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="q-test: sew-getriebe-ba p. 1 is listed twice"):
        load_eval(f)
