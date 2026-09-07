"""Builders and readers shared by several test modules.

Deliberately a plain module rather than `conftest.py`: pytest hands out
fixtures from there automatically, but not ordinary functions, and importing
`conftest` directly is not what it is meant for. An explicit import says where
the helper comes from.
"""

import io
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from anlagen_copilot.corpus import CorpusDocument


def make_document(**overrides: object) -> CorpusDocument:
    """Builds a minimally valid CorpusDocument, mandatory fields as placeholders.

    Tests that care about a single field then do not have to spell out every
    mandatory one on each call. `pages` belongs at the call site wherever it
    matters — what counts as a sensible page count differs per test, and a
    default hidden in here once differed between two copies of this helper.
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


def make_pdf_bytes(pages: int, *, password: str | None = None) -> bytes:
    """Builds a structurally valid PDF of `pages` blank pages, in memory.

    Blank pages, which is all most callers need — counting them, keeping their
    numbers, deciding whether a response is a PDF at all. Where the text itself
    matters, `make_text_pdf()` is the sibling; it costs a hand-written content
    stream and stays out of the way here.

    The size is A4 in points (595x842), the unit PDF actually uses. Nothing
    here depends on it; it is spelled correctly so the numbers do not read as
    millimetres.

    `password` encrypts the file with a *user* password, and whether it is
    empty picks the branch: `extract_pages()` opens encrypted documents with
    `decrypt("")`, so `""` gets in and anything else does not.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password is not None:
        writer.encrypt(user_password=password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_pdf(path: Path, pages: int, *, password: str | None = None) -> None:
    """Writes `make_pdf_bytes()` to `path`, for callers that need it on disk."""
    path.write_bytes(make_pdf_bytes(pages, password=password))


def make_text_pdf(path: Path, texts: Sequence[str | None]) -> None:
    """Writes a PDF with one page per entry; `None` gives a page without text.

    The mix is the point. `make_pdf_bytes()` only produces pages that extract
    to `""`, so everything downstream of the question "has this page any text"
    is unreachable with it — the usable/skipped split in `ingest_document()`,
    the count it warns with, and every INSERT behind them.

    pypdf has no API for writing text, hence the content stream by hand:
    `BT /F1 24 Tf 72 700 Td (…) Tj ET` reads as "begin text, pick font and
    size, place the cursor, show the string, end text". Nobody would want to
    look at the result; extraction finds the string, which is the whole job.

    Stream and resources go onto the page directly rather than through
    `PdfWriter._add_object()`. pypdf adds the indirection on write, and the
    public path is the one that keeps working.
    """
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in texts:
        page = writer.add_blank_page(width=595, height=842)
        if text is None:
            continue

        # `(`, `)` and `\` end a PDF string literal. Left unescaped, a page
        # holding "Abschnitt 5) Wartung" makes *this builder* produce bytes
        # that PdfReader rejects — a PdfReadError that reads exactly like a
        # defect in the code under test.
        escaped = text
        for char in ("\\", "(", ")"):
            escaped = escaped.replace(char, "\\" + char)

        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 24 Tf 72 700 Td ({escaped}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )

    writer.write(path)


def was_logged(caplog: pytest.LogCaptureFixture, level: int, text: str) -> bool:
    """Whether some record at `level` carries `text` in its formatted message.

    `text` is matched as a substring, so a caller can pin the part that
    matters — usually the numbers — without repeating the whole sentence.
    `level` is compared exactly: a line that slips from WARNING to DEBUG still
    says the same thing while nobody sees it any more.

    What gets captured at all is the caller's decision, through
    `caplog.at_level(...)`; this only looks at what landed there.

    Two things the substring costs, worth knowing before leaning on it: the
    check follows the wording, so rephrasing a message breaks it — keep the
    fragment short and numeric. And a bool carries no diff, so pytest can only
    report `assert False`; pass `caplog.text` as the assertion message to get
    the actual log printed alongside.
    """
    return any(record.levelno == level and text in record.getMessage() for record in caplog.records)
