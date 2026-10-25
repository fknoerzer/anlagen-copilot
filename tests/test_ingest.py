import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from docling.datamodel.base_models import ConversionStatus
from docling.exceptions import ConversionError
from helpers import (
    NO_CLIENT,
    REJECTED,
    UNAUTHORIZED,
    fake_embed,
    make_document,
    make_pdf,
    was_logged,
)
from openai import AuthenticationError
from pgvector import Vector

from anlagen_copilot import ingest
from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.ingest import (
    extract_document,
    extract_pages,
    extract_pages_docling,
    ingest_document,
    strip_boilerplate,
)


def _verbs(conn: MagicMock) -> list[str]:
    """First keyword of each statement executed, in order — the rest is indentation."""
    return [call.args[0].strip().split()[0] for call in conn.execute.call_args_list]


def _params(conn: MagicMock) -> list[tuple[object, ...]]:
    """The parameter tuple of each statement, in the same order."""
    return [call.args[1] for call in conn.execute.call_args_list]


@pytest.mark.docling
def test_extract_pages_docling_keeps_original_page_numbers_in_an_excerpt(tmp_path: Path) -> None:
    """Page 2 stays 2, not renumbered to 1.

    `chunks.page` is the page an answer cites; renumbering would send every
    reader of an excerpted manual astray with nothing failing on the way.
    """
    make_pdf(tmp_path / "doc.pdf", pages=4)
    doc = make_document(filename="doc.pdf", excerpt_pages=(2, 4))

    pages = extract_pages_docling(doc, tmp_path)

    assert pages == [(2, ""), (3, ""), (4, "")]


@pytest.mark.docling
def test_extract_pages_docling_keeps_the_text_of_a_drawing() -> None:
    """The nameplate on p. 22 is a vector drawing; its text must reach the chunk.

    Without `traverse_pictures` the Markdown export drops it for an image
    placeholder, and nothing fails. The PDF is downloaded, not committed, so the
    test skips where the corpus has not been fetched.
    """
    corpus = load_corpus()
    document = next(d for d in corpus.documents if d.id == "sew-getriebe-ba")
    if not (corpus.corpus.raw_dir / document.filename).is_file():
        pytest.skip("corpus not downloaded")

    pages = extract_pages_docling(
        document.model_copy(update={"excerpt_pages": (22, 22)}), corpus.corpus.raw_dir
    )

    [(page, text)] = pages
    assert page == 22
    assert "Th.Kl. 130(B)" in text
    assert "<!-- image -->" not in text


@pytest.mark.docling
def test_extract_pages_docling_restores_the_umlauts_of_the_catalogue() -> None:
    """The catalogue's declared defect is repaired: p. 159 reads "müssen", not "m�ssen"."""
    corpus = load_corpus()
    document = next(d for d in corpus.documents if d.id == "sew-katalog-projektierung")
    if not (corpus.corpus.raw_dir / document.filename).is_file():
        pytest.skip("corpus not downloaded")

    [(_, text)] = extract_pages_docling(
        document.model_copy(update={"excerpt_pages": (159, 159)}), corpus.corpus.raw_dir
    )

    assert "müssen Sie zusätzlich angeben" in text


class _FakeDocument:
    """Stands in for a `DoclingDocument`: one prepared Markdown text per page."""

    def __init__(self, texts: dict[int, str]) -> None:
        self.pages = texts
        self._texts = texts

    def export_to_markdown(self, *, page_no: int, **options: object) -> str:
        return self._texts[page_no]


class _FakeConverter:
    """Stands in for Docling's converter: returns a prepared result or raises."""

    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def convert(self, source: Path, page_range: tuple[int, int]) -> object:
        if self._error is not None:
            raise self._error
        return self._result


def _patch_converter(monkeypatch: pytest.MonkeyPatch, converter: _FakeConverter) -> list[bool]:
    """Replaces `_converter`; returns the `pdfium` values it was asked for, in order."""
    asked: list[bool] = []

    def fake(*, pdfium: bool) -> _FakeConverter:
        asked.append(pdfium)
        return converter

    monkeypatch.setattr(ingest, "_converter", fake)
    return asked


def _converted(texts: dict[int, str]) -> SimpleNamespace:
    return SimpleNamespace(
        status=ConversionStatus.SUCCESS, errors=[], document=_FakeDocument(texts)
    )


def test_extract_pages_docling_rejects_a_partial_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 005: Docling returns a partial result without raising; pages it lost would be skipped."""
    partial = SimpleNamespace(
        status=ConversionStatus.PARTIAL_SUCCESS,
        errors=[SimpleNamespace(error_message="page 3 failed")],
    )
    _patch_converter(monkeypatch, _FakeConverter(result=partial))

    with pytest.raises(DocumentError, match="partial_success: page 3 failed"):
        extract_pages_docling(make_document(filename="doc.pdf"), tmp_path)


def test_extract_pages_docling_turns_a_conversion_error_into_a_document_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller handles one error type for both strategies, as for pypdf."""
    _patch_converter(monkeypatch, _FakeConverter(error=ConversionError("unreadable")))

    with pytest.raises(DocumentError, match="PDF not convertible"):
        extract_pages_docling(make_document(filename="doc.pdf"), tmp_path)


def test_extract_pages_docling_repairs_a_cp1252_font_read_as_macroman(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared defect picks pypdfium2 and maps the misread characters home, and only those."""
    garbled = "Sie m¸ssen zus‰tzlich angeben ï Schrumpfscheibe — Seite 164 → SPIROPLANÆ"
    asked = _patch_converter(monkeypatch, _FakeConverter(result=_converted({159: garbled})))
    document = make_document(filename="doc.pdf", text_encoding_defect="cp1252_as_macroman")

    pages = extract_pages_docling(document, tmp_path)

    assert asked == [True]
    # "—" and "→" come from fonts that arrive correctly and stay as they are.
    assert pages == [
        (159, "Sie müssen zusätzlich angeben • Schrumpfscheibe — Seite 164 → SPIROPLAN®")
    ]


def test_extract_pages_docling_leaves_a_document_without_a_declared_defect_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a clean document the same characters are real: a per mille sign stays one."""
    asked = _patch_converter(monkeypatch, _FakeConverter(result=_converted({1: "Steigung 2 ‰"})))

    pages = extract_pages_docling(make_document(filename="doc.pdf"), tmp_path)

    assert asked == [False]
    assert pages == [(1, "Steigung 2 ‰")]


def test_extract_pages_docling_fails_when_the_declared_repair_leaves_characters_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 005: a defect that is not the declared one must not reach the index half repaired."""
    _patch_converter(monkeypatch, _FakeConverter(result=_converted({7: "m�ssen"})))
    document = make_document(filename="doc.pdf", text_encoding_defect="cp1252_as_macroman")

    with pytest.raises(DocumentError, match="page 7 still has 1 lost characters"):
        extract_pages_docling(document, tmp_path)


def test_extract_pages_docling_logs_lost_characters_without_a_declared_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Without a declaration the page goes in, and the count says where to look."""
    _patch_converter(monkeypatch, _FakeConverter(result=_converted({7: "m�ssen"})))

    with caplog.at_level(logging.WARNING):
        extract_pages_docling(make_document(filename="doc.pdf"), tmp_path)

    assert was_logged(caplog, logging.WARNING, "page 7 has 1 characters lost"), caplog.text


def test_extract_pages_keeps_original_page_numbers_in_an_excerpt(tmp_path: Path) -> None:
    """Page 2 stays 2, not renumbered to 1.

    `chunks.page` is the page an answer cites; renumbering would send every
    reader of an excerpted manual astray with nothing failing on the way.
    """
    make_pdf(tmp_path / "doc.pdf", pages=4)
    doc = make_document(filename="doc.pdf", excerpt_pages=(2, 4))

    pages = extract_pages(doc, tmp_path)

    assert pages == [(2, ""), (3, ""), (4, "")]


def test_extract_pages_reads_every_page_without_an_excerpt(tmp_path: Path) -> None:
    """No excerpt means the whole file, numbered from 1.

    The empty strings are the second claim: a page without text comes back as
    a page. Dropping and counting it is `ingest_document()`'s job.
    """
    make_pdf(tmp_path / "doc.pdf", pages=4)
    doc = make_document(filename="doc.pdf")

    pages = extract_pages(doc, tmp_path)

    assert pages == [(1, ""), (2, ""), (3, ""), (4, "")]


def test_extract_pages_returns_nothing_for_a_file_without_pages(tmp_path: Path) -> None:
    """An empty range is reported truthfully, not as an error.

    Refusing to overwrite an indexed document with nothing is a decision about
    writing and belongs to `ingest_document()` — which today does not make it,
    see TODO C.
    """
    make_pdf(tmp_path / "doc.pdf", pages=0)
    doc = make_document(filename="doc.pdf")

    assert extract_pages(doc, tmp_path) == []


def test_extract_pages_opens_an_encrypted_pdf_with_an_empty_password(tmp_path: Path) -> None:
    """The path half the corpus takes: `encrypted: true`, and `decrypt("")` gets in.

    Three of six manuals in `corpus.yaml` are encrypted this way, so this is
    the normal case rather than an edge one — and until now only its failure
    was covered.
    """
    make_pdf(tmp_path / "doc.pdf", pages=2, password="")
    doc = make_document(filename="doc.pdf", encrypted=True)

    assert extract_pages(doc, tmp_path) == [(1, ""), (2, "")]


def test_extract_pages_rejects_a_pdf_that_needs_a_password(tmp_path: Path) -> None:
    """`encrypted: true` plus a real password means `decrypt("")` fails.

    A plain PDF would raise `PdfReadError("Not encrypted file")` and end up as
    the *other* `DocumentError` — same type, wrong branch, green test. Hence a
    genuinely encrypted file, and `match=` to tell the two apart.
    """
    make_pdf(tmp_path / "doc.pdf", pages=4, password="not-empty")
    doc = make_document(filename="doc.pdf", encrypted=True)

    with pytest.raises(DocumentError, match="decryption"):
        extract_pages(doc, tmp_path)


def test_extract_pages_rejects_content_that_is_not_a_pdf(tmp_path: Path) -> None:
    (tmp_path / "doc.pdf").write_bytes(b"<!DOCTYPE html><html>not a pdf</html>")
    doc = make_document(filename="doc.pdf")

    with pytest.raises(DocumentError, match="not readable"):
        extract_pages(doc, tmp_path)


def test_strip_boilerplate_removes_a_line_that_appears_on_every_page() -> None:
    """A header on all ten pages goes, the content under it stays.

    The content lines differ in words, not only in digits: "Inhalt 1" to
    "Inhalt 10" normalize to one line and would count as boilerplate themselves.
    """
    contents = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{text}")
        for n, text in enumerate(contents, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == list(enumerate(contents, start=1))


def test_strip_boilerplate_keeps_a_line_below_the_threshold() -> None:
    """A line on 8 of 10 pages, 80 %, is frequent content and stays.

    Modelled on "Reaktion: KEINE" in the Siemens fault list. A threshold set too
    low would remove it.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    contents = [
        f"{word}\nReaktion: KEINE" if n <= 8 else word for n, word in enumerate(words, start=1)
    ]

    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{text}")
        for n, text in enumerate(contents, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == list(enumerate(contents, start=1))


def test_strip_boilerplate_removes_a_header_missing_from_some_pages() -> None:
    """A header on 9 of 10 pages, 90 %, still goes.

    Real headers rarely reach every page: sew-katalog-projektierung carries its own
    on 92 %, siemens-g120c-liste on 89 %. A threshold set too high would keep them.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{word}" if n <= 9 else word)
        for n, word in enumerate(words, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == list(enumerate(words, start=1))


def test_strip_boilerplate_counts_a_line_once_per_page() -> None:
    """A line repeated on few pages stays, however often it repeats there.

    Ten times on each of 2 of 10 pages is 20 occurrences but 20 % of the pages.
    Counted per occurrence instead of per page, it would clear the threshold.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    contents = [
        word + "\nReaktion: KEINE" * 10 if n <= 2 else word for n, word in enumerate(words, start=1)
    ]
    pages = list(enumerate(contents, start=1))

    result = strip_boilerplate(pages)

    assert result == pages


def test_strip_boilerplate_keeps_a_line_without_letters() -> None:
    """A line of numbers stays even on every page; it is a table value, not a header.

    "-20 +40" normalizes to "-# +", which has no letter and is never counted.
    Temperature ranges like it stand on 62 % of the pages of sew-schmierstoffe.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{word}\n-20 +40")
        for n, word in enumerate(words, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == [(n, f"{word}\n-20 +40") for n, word in enumerate(words, start=1)]


def test_strip_boilerplate_removes_a_header_whose_page_number_changes_sides() -> None:
    """A header numbered left on even pages and right on odd ones counts as one line.

    Each raw variant is unique; only the normalization makes them one line on 100 %.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]

    pages = [
        (
            n,
            f"{n}Betriebsanleitung – Drehstrommotoren\n{word}"
            if n % 2 == 0
            else f"Betriebsanleitung – Drehstrommotoren {n}\n{word}",
        )
        for n, word in enumerate(words, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == list(enumerate(words, start=1))


def test_strip_boilerplate_leaves_a_short_document_alone() -> None:
    """Below `_BOILERPLATE_MIN_PAGES` nothing is removed, not even a line on every page.

    On three pages, "all of them" is a count a single chapter title reaches by chance.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
    ]

    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{word}")
        for n, word in enumerate(words, start=1)
    ]

    result = strip_boilerplate(pages)

    assert result == pages


def test_ingest_document_writes_one_row_per_usable_page(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Delete what was there, insert what is there now.

    Only `embed()` is patched — the one collaborator that cannot run here. Page
    1, which has no text, must reach no INSERT: the usable/skipped split,
    asserted by absence.
    """
    monkeypatch.setattr(ingest, "embed", fake_embed)
    pages = [(1, ""), (2, "zweite Seite"), (3, "dritte Seite")]
    conn = MagicMock()

    with caplog.at_level(logging.WARNING):
        ingest_document(NO_CLIENT, make_document(id="test-doc"), conn, pages)

    assert _verbs(conn) == ["DELETE", "INSERT", "INSERT"]
    assert _params(conn) == [
        ("naive", "test-doc"),
        ("naive", "test-doc", 2, "zweite Seite", Vector([0.5] * 4)),
        ("naive", "test-doc", 3, "dritte Seite", Vector([0.5] * 4)),
    ]
    # The skipped page is counted nowhere else — not in the return value, not
    # in `chunks`, not in the statements above.
    assert was_logged(caplog, logging.WARNING, "skipped 1 of 3 pages"), caplog.text


def test_extract_document_returns_pages_without_their_running_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What reaches `ingest_document()` is the page without its header.

    Ten pages, because below `_BOILERPLATE_MIN_PAGES` stripping leaves a document
    alone — which is why no other test here would notice the call going missing.
    `extract_pages` is patched so the pages can carry two lines each.
    """
    words = [
        "Motor",
        "Bremse",
        "Getriebe",
        "Lager",
        "Welle",
        "Kupplung",
        "Dichtung",
        "Lüfter",
        "Klemme",
        "Sensor",
    ]
    pages = [
        (n, f"Betriebsanleitung – Drehstrommotoren\n{word}")
        for n, word in enumerate(words, start=1)
    ]
    monkeypatch.setattr(ingest, "extract_pages", Mock(return_value=pages))

    extracted = extract_document(make_document(), tmp_path)

    assert [text for _, text in extracted] == words


def test_extract_document_reads_with_docling_under_the_advanced_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ingest, "get_settings", Mock(return_value=SimpleNamespace(ingest_strategy="advanced"))
    )
    monkeypatch.setattr(ingest, "extract_pages_docling", Mock(return_value=[(1, "Seite A")]))
    monkeypatch.setattr(ingest, "extract_pages", Mock(side_effect=AssertionError("pypdf")))

    assert extract_document(make_document(), tmp_path) == [(1, "Seite A")]


def test_ingest_document_aborts_when_no_page_carries_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scan-only manual is dropped before any statement runs.

    Its pages extract to `""`, so the guard ahead of the `DELETE` hits. The
    embedding mock raises if it is reached; it is not.
    """
    monkeypatch.setattr(ingest, "embed", Mock(side_effect=AssertionError("must not embed")))
    conn = MagicMock()

    with pytest.raises(DocumentError, match="no page with extractable text"):
        ingest_document(NO_CLIENT, make_document(id="test-doc"), conn, [(1, ""), (2, "")])

    assert _verbs(conn) == []


def test_ingest_document_aborts_when_every_page_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document that keeps no page fails rather than passing as an empty success.

    Its own message: the guard above would match "no page with extractable
    text" too, and only one of the two means it. The `DELETE` has run by then
    and the mock sees it — taking it back is the caller's transaction.
    """
    monkeypatch.setattr(ingest, "embed", Mock(side_effect=REJECTED))
    conn = MagicMock()

    with pytest.raises(DocumentError, match="all 2 pages rejected by the embedding model"):
        ingest_document(
            NO_CLIENT, make_document(id="test-doc"), conn, [(1, "erste Seite"), (2, "zweite Seite")]
        )

    assert _verbs(conn) == ["DELETE"]


def test_ingest_document_skips_a_rejected_page_and_keeps_the_rest(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One page lost, not the document — the claim the `continue` makes.

    Needs a page that survives: with every page rejected, skipping and aborting
    look the same from out here, so `break` would pass just as well.
    """
    monkeypatch.setattr(ingest, "embed", fake_embed)
    pages = [(1, ""), (2, "zu lang"), (3, "zweite Seite")]
    conn = MagicMock()

    with caplog.at_level(logging.WARNING):
        ingest_document(NO_CLIENT, make_document(id="test-doc"), conn, pages)

    assert _verbs(conn) == ["DELETE", "INSERT"]
    assert _params(conn) == [
        ("naive", "test-doc"),
        ("naive", "test-doc", 3, "zweite Seite", Vector([0.5] * 4)),
    ]
    # The textless page keeps the two counts apart: 1 of 3 pages, then 1 of the
    # 2 that were usable. Without it both would read "1 of 2" and confusing
    # `len(usable)` with `len(pages)` would go unnoticed.
    assert was_logged(caplog, logging.WARNING, "skipped 1 of 3 pages"), caplog.text
    assert was_logged(caplog, logging.WARNING, "1 of 2 pages rejected"), caplog.text


def test_ingest_document_lets_a_failure_of_the_whole_run_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counter-check to the rejection tests above: only `BadRequestError` is caught.

    Same shape of failure, opposite handling. A rejected page is a statement
    about that page, a bad key is one about every page there will ever be —
    catching it would turn a dead run into a green one that quietly empties
    the index, document after document.

    Nothing in the positive tests would notice a `except OpenAIError` here;
    they would all still pass. This is the only test that would not.
    """
    monkeypatch.setattr(ingest, "embed", Mock(side_effect=UNAUTHORIZED))
    conn = MagicMock()

    with pytest.raises(AuthenticationError):
        ingest_document(
            NO_CLIENT, make_document(id="test-doc"), conn, [(1, "erste Seite"), (2, "zweite Seite")]
        )

    # The DELETE is already out when the exception leaves, and no INSERT
    # follows it. Undoing that is the caller's transaction in `cli.main()`,
    # which is exactly what the boundary there is for.
    assert _verbs(conn) == ["DELETE"]
