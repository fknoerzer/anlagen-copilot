"""Tests for anlagen_copilot.corpus: loading/validating the corpus manifest."""

from pathlib import Path

import pytest
import yaml
from helpers import make_document

from anlagen_copilot.corpus import load_corpus


def test_load_corpus_succeeds(tmp_path: Path) -> None:
    """Uses hand-written YAML on purpose rather than make_document().

    make_document() returns an already validated CorpusDocument object, not
    YAML — but this test is about the file and parsing pipeline of
    load_corpus(), as close as possible to what is actually written by hand in
    corpus.yaml, including YAML pitfalls such as indentation.
    """
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
    """Regression check: data/raw/corpus.yaml stays valid against the schema.

    Deliberately without a hard document count, since the corpus is meant to
    grow — checks only structural invariants that must hold at any corpus size.
    """
    corpus = load_corpus()

    ids = [doc.id for doc in corpus.documents]
    assert len(ids) > 0
    assert len(ids) == len(set(ids))


def test_load_corpus_rejects_broken_yaml(tmp_path: Path) -> None:
    f = tmp_path / "corpus.yaml"
    f.write_text("documents: [{id: a\n", encoding="utf-8")  # unbalanced bracket

    with pytest.raises(yaml.YAMLError):
        load_corpus(f)


def test_load_corpus_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path / "does-not-exist.yaml")


def test_excerpt_pages_none_is_allowed() -> None:
    doc = make_document(pages=100, excerpt_pages=None)

    assert doc.excerpt_pages is None


def test_excerpt_pages_accepts_valid_range() -> None:
    doc = make_document(pages=100, excerpt_pages=(10, 20))

    assert doc.excerpt_pages == (10, 20)


def test_excerpt_pages_rejects_start_below_one() -> None:
    with pytest.raises(ValueError, match="first page"):
        make_document(pages=100, excerpt_pages=(0, 10))


def test_excerpt_pages_rejects_start_not_before_end() -> None:
    with pytest.raises(ValueError, match="must be less than end"):
        make_document(pages=100, excerpt_pages=(20, 10))


def test_excerpt_pages_rejects_end_beyond_total_pages() -> None:
    with pytest.raises(ValueError, match="past the last page"):
        make_document(pages=100, excerpt_pages=(10, 200))
