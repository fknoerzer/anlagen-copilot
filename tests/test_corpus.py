"""Tests für anlagen_copilot.corpus: Laden/Validieren des Korpus-Manifests."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from anlagen_copilot.corpus import CorpusDocument, load_corpus


def _make_document(**overrides: object) -> CorpusDocument:
    """Baut ein minimal gültiges CorpusDocument, Pflichtfelder mit Platzhaltern.

    Tests, die nur ein einzelnes Feld prüfen (z. B. excerpt_pages), müssen so
    nicht bei jedem Aufruf alle Pflichtfelder von CorpusDocument ausschreiben.
    """
    defaults: dict[str, object] = {
        "id": "test-doc",
        "filename": "test-doc.pdf",
        "title": "Testdokument",
        "manufacturer": "Testhersteller",
        "doc_type": "betriebsanleitung",
        "domain": "mechanik",
        "pages": 100,
        "url": "https://example.com/test-doc.pdf",
        "retrieved": date(2026, 7, 29),
    }
    defaults.update(overrides)
    return CorpusDocument.model_validate(defaults)


def test_load_corpus_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "corpus.yaml"
    f.write_text(
        """
corpus:
  name: Test-Korpus
  language: de
  description: Minimaler Korpus für Tests.
  raw_dir: data/raw
documents:
  - id: doc-a
    filename: doc-a.pdf
    title: Dokument A
    manufacturer: Testhersteller
    doc_type: betriebsanleitung
    domain: mechanik
    pages: 10
    url: https://example.com/doc-a.pdf
    retrieved: 2026-07-29
cross_references: []
""",
        encoding="utf-8",
    )

    corpus = load_corpus(f)

    assert len(corpus.documents) == 1
    assert corpus.corpus.language == "de"


def test_real_corpus_yaml_is_valid() -> None:
    """Regressionscheck: data/raw/corpus.yaml bleibt gegen das Schema valide.

    Bewusst ohne harte Dokumentanzahl, da der Korpus wachsen soll — prüft
    nur strukturelle Invarianten, die bei jeder Korpusgröße gelten müssen.
    """
    corpus = load_corpus()

    ids = [doc.id for doc in corpus.documents]
    assert len(ids) > 0
    assert len(ids) == len(set(ids))


def test_load_corpus_rejects_broken_yaml(tmp_path: Path) -> None:
    f = tmp_path / "corpus.yaml"
    f.write_text("documents: [{id: a\n", encoding="utf-8")  # unbalancierte Klammer

    with pytest.raises(yaml.YAMLError):
        load_corpus(f)


def test_load_corpus_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "gibtsnicht.yaml")


def test_excerpt_pages_none_is_allowed() -> None:
    doc = _make_document(pages=100, excerpt_pages=None)

    assert doc.excerpt_pages is None


def test_excerpt_pages_accepts_valid_range() -> None:
    doc = _make_document(pages=100, excerpt_pages=(10, 20))

    assert doc.excerpt_pages == (10, 20)


def test_excerpt_pages_rejects_start_below_one() -> None:
    with pytest.raises(ValueError, match="Startseite"):
        _make_document(pages=100, excerpt_pages=(0, 10))


def test_excerpt_pages_rejects_start_not_before_end() -> None:
    with pytest.raises(ValueError, match="kleiner als Ende"):
        _make_document(pages=100, excerpt_pages=(20, 10))


def test_excerpt_pages_rejects_end_beyond_total_pages() -> None:
    with pytest.raises(ValueError, match="letzten Seite"):
        _make_document(pages=100, excerpt_pages=(10, 200))
