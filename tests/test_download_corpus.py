import io
from datetime import date
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.scripts.download_corpus import check_pages, download_document


def _make_pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=210, height=297)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_pdf(path: Path, pages: int) -> None:
    path.write_bytes(_make_pdf_bytes(pages))


def _make_document(**overrides: object) -> CorpusDocument:
    defaults: dict[str, object] = {
        "id": "test-doc",
        "filename": "test-doc.pdf",
        "title": "Testdokument",
        "manufacturer": "Testhersteller",
        "doc_type": "betriebsanleitung",
        "domain": "mechanik",
        "pages": 2,
        "url": "https://example.com/test-doc.pdf",
        "retrieved": date(2026, 7, 29),
    }
    defaults.update(overrides)
    return CorpusDocument.model_validate(defaults)


def _fake_response(status_code: int, content: bytes = b"") -> httpx.Response:
    """A real httpx.Response instead of a fake, so raise_for_status() really behaves."""
    request = httpx.Request("GET", "https://example.com/test-doc.pdf")
    return httpx.Response(status_code, content=content, request=request)


def test_check_pages_accepts_matching_count(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    _make_pdf(pdf_path, pages=3)

    check_pages(3, pdf_path, label=pdf_path.name)  # must not raise


def test_check_pages_rejects_mismatch(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    _make_pdf(pdf_path, pages=3)

    with pytest.raises(DocumentError, match="expected 5"):
        check_pages(5, pdf_path, label=pdf_path.name)


def test_download_document_skips_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="existing.pdf")
    (tmp_path / "existing.pdf").write_bytes(b"already present")

    def fail_if_called(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("httpx.get should not have been called")

    monkeypatch.setattr(httpx, "get", fail_if_called)

    download_document(doc, tmp_path)

    assert (tmp_path / "existing.pdf").read_bytes() == b"already present"


def test_download_document_writes_file_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="new.pdf", pages=2)
    pdf_bytes = _make_pdf_bytes(pages=2)

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, pdf_bytes))

    download_document(doc, tmp_path)

    target = tmp_path / "new.pdf"
    assert target.is_file()
    assert target.read_bytes() == pdf_bytes


def test_download_document_raises_on_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="broken.pdf")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(404))

    with pytest.raises(DocumentError, match="server responded 404"):
        download_document(doc, tmp_path)

    assert not (tmp_path / "broken.pdf").is_file()


def test_download_document_raises_on_page_mismatch_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="wrong-pages.pdf", pages=5)
    pdf_bytes = _make_pdf_bytes(pages=2)

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, pdf_bytes))

    with pytest.raises(DocumentError, match="expected 5"):
        download_document(doc, tmp_path)

    assert not (tmp_path / "wrong-pages.pdf").is_file()
