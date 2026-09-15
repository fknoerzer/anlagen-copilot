import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from helpers import (
    NO_CLIENT,
    REJECTED,
    UNAUTHORIZED,
    fake_embed,
    make_document,
    make_pdf,
    make_text_pdf,
    was_logged,
)
from openai import AuthenticationError
from pgvector import Vector

from anlagen_copilot import ingest
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.ingest import extract_pages, ingest_document, strip_boilerplate


def _verbs(conn: MagicMock) -> list[str]:
    """First keyword of each statement executed, in order — the rest is indentation."""
    return [call.args[0].strip().split()[0] for call in conn.execute.call_args_list]


def _params(conn: MagicMock) -> list[tuple[object, ...]]:
    """The parameter tuple of each statement, in the same order."""
    return [call.args[1] for call in conn.execute.call_args_list]


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Delete what was there, insert what is there now.

    Only `embed()` is patched — the one collaborator that cannot run here. The
    page numbers therefore come from real extraction, and page 1, which has no
    text, must reach no INSERT: the usable/skipped split, asserted by absence.
    """
    monkeypatch.setattr(ingest, "embed", fake_embed)
    make_text_pdf(tmp_path / "doc.pdf", [None, "zweite Seite", "dritte Seite"])
    doc = make_document(id="test-doc", filename="doc.pdf")
    conn = MagicMock()

    with caplog.at_level(logging.WARNING):
        ingest_document(NO_CLIENT, doc, conn, tmp_path)

    assert _verbs(conn) == ["DELETE", "INSERT", "INSERT"]
    assert _params(conn) == [
        ("naive", "test-doc"),
        ("naive", "test-doc", 2, "zweite Seite", Vector([0.5] * 4)),
        ("naive", "test-doc", 3, "dritte Seite", Vector([0.5] * 4)),
    ]
    # The skipped page is counted nowhere else — not in the return value, not
    # in `chunks`, not in the statements above.
    assert was_logged(caplog, logging.WARNING, "skipped 1 of 3 pages"), caplog.text


def test_ingest_document_writes_pages_without_their_running_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What reaches the INSERT is the page without its header.

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
    monkeypatch.setattr(ingest, "embed", fake_embed)
    conn = MagicMock()

    ingest_document(NO_CLIENT, make_document(id="test-doc"), conn, tmp_path)

    # The first statement is the DELETE; index 3 of each INSERT is `content`.
    assert [params[3] for params in _params(conn)[1:]] == words


def test_ingest_document_aborts_when_no_page_carries_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan-only manual is dropped before any statement runs.

    `make_pdf()` writes pages that extract to `""`, so the guard ahead of the
    `DELETE` hits. The embedding mock raises if it is reached; it is not.
    """
    monkeypatch.setattr(ingest, "embed", Mock(side_effect=AssertionError("must not embed")))
    make_pdf(tmp_path / "doc.pdf", pages=2)
    doc = make_document(id="test-doc", filename="doc.pdf")
    conn = MagicMock()

    with pytest.raises(DocumentError, match="no page with extractable text"):
        ingest_document(NO_CLIENT, doc, conn, tmp_path)

    assert _verbs(conn) == []


def test_ingest_document_aborts_when_every_page_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document that keeps no page fails rather than passing as an empty success.

    Its own message: the guard above would match "no page with extractable
    text" too, and only one of the two means it. The `DELETE` has run by then
    and the mock sees it — taking it back is the caller's transaction.
    """
    monkeypatch.setattr(ingest, "embed", Mock(side_effect=REJECTED))
    make_text_pdf(tmp_path / "doc.pdf", ["erste Seite", "zweite Seite"])
    doc = make_document(id="test-doc", filename="doc.pdf")
    conn = MagicMock()

    with pytest.raises(DocumentError, match="all 2 pages rejected by the embedding model"):
        ingest_document(NO_CLIENT, doc, conn, tmp_path)

    assert _verbs(conn) == ["DELETE"]


def test_ingest_document_skips_a_rejected_page_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One page lost, not the document — the claim the `continue` makes.

    Needs a page that survives: with every page rejected, skipping and aborting
    look the same from out here, so `break` would pass just as well.
    """
    monkeypatch.setattr(ingest, "embed", fake_embed)
    make_text_pdf(tmp_path / "doc.pdf", [None, "zu lang", "zweite Seite"])
    doc = make_document(id="test-doc", filename="doc.pdf")
    conn = MagicMock()

    with caplog.at_level(logging.WARNING):
        ingest_document(NO_CLIENT, doc, conn, tmp_path)

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    make_text_pdf(tmp_path / "doc.pdf", ["erste Seite", "zweite Seite"])
    doc = make_document(id="test-doc", filename="doc.pdf")
    conn = MagicMock()

    with pytest.raises(AuthenticationError):
        ingest_document(NO_CLIENT, doc, conn, tmp_path)

    # The DELETE is already out when the exception leaves, and no INSERT
    # follows it. Undoing that is the caller's transaction in `cli.main()`,
    # which is exactly what the boundary there is for.
    assert _verbs(conn) == ["DELETE"]
