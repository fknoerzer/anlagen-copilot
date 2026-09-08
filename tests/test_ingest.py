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
from anlagen_copilot.ingest import extract_pages, ingest_document


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


def test_ingest_document_aborts_when_no_page_carries_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan-only manual ends the document before the table is touched.

    `make_pdf()` writes pages that extract to `""`, so `usable` is empty — the
    guard ahead of the `DELETE`, which is why not a single statement runs. The
    embedding mock would raise if it were reached; it never is.
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
    """A document that keeps no page fails; it does not pass as an empty success.

    Pages with text that the model turns down — the other reason to give up,
    and a different message from the test above, so a log says which of the two
    happened. Both would match "no page with extractable text"; only one of
    them means it.

    The `DELETE` has run by then and the mock sees it. Taking it back is the
    caller's transaction, not this function — what must not appear is an
    INSERT.
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
