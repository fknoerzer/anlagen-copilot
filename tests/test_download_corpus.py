import io
from datetime import date
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.scripts.download_corpus import check_pages, download_document

# What a download portal serves instead of the file when it wants a browser:
# HTML, at status 200. raise_for_status() has nothing to complain about.
_CHALLENGE_PAGE = b"<!DOCTYPE html><html><body>Please enable JavaScript</body></html>"


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


def test_check_pages_rejects_content_that_is_not_a_pdf(tmp_path: Path) -> None:
    not_a_pdf = tmp_path / "challenge.pdf"
    not_a_pdf.write_bytes(_CHALLENGE_PAGE)

    with pytest.raises(DocumentError, match="no readable PDF"):
        check_pages(2, not_a_pdf, label=not_a_pdf.name)


def test_download_document_rejects_challenge_page_served_at_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="challenge.pdf")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, _CHALLENGE_PAGE))

    with pytest.raises(DocumentError, match="no readable PDF"):
        download_document(doc, tmp_path)

    assert not (tmp_path / "challenge.pdf").is_file()


def test_download_document_raises_on_redirect_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="looping.pdf")

    def raise_redirect_loop(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.TooManyRedirects("exceeded maximum allowed redirects")

    monkeypatch.setattr(httpx, "get", raise_redirect_loop)

    with pytest.raises(DocumentError, match="redirect loop"):
        download_document(doc, tmp_path)

    assert not (tmp_path / "looping.pdf").is_file()


def test_download_document_leaves_no_partial_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="new.pdf", pages=2)

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, _make_pdf_bytes(2)))

    download_document(doc, tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["new.pdf"]


def test_download_document_writes_no_target_file_when_the_write_is_cut_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="new.pdf", pages=2)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, _make_pdf_bytes(2)))

    # Half the bytes land, then the disk gives up. Writing straight to the
    # target would leave that half behind under the real name, and the next run
    # would adopt it through the is_file() check at the top. The .part that
    # takes the hit instead is cleaned up on the way out, so the directory is
    # left exactly as it was found.
    write_bytes = Path.write_bytes

    def write_half_then_fail(self: Path, data: bytes) -> int:
        write_bytes(self, data[: len(data) // 2])
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_bytes", write_half_then_fail)

    with pytest.raises(OSError, match="No space left"):
        download_document(doc, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_download_document_creates_a_missing_raw_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="new.pdf", pages=2)
    raw_dir = tmp_path / "data" / "raw"

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, _make_pdf_bytes(2)))

    download_document(doc, raw_dir)

    assert (raw_dir / "new.pdf").is_file()


def test_download_document_follows_redirects_and_identifies_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _make_document(filename="new.pdf", pages=2)
    calls: list[dict[str, object]] = []

    def record(*args: object, **kwargs: object) -> httpx.Response:
        calls.append(kwargs)
        return _fake_response(200, _make_pdf_bytes(2))

    monkeypatch.setattr(httpx, "get", record)

    download_document(doc, tmp_path)

    # kwargs comes in as dict[str, object], so the header dict has to be
    # narrowed before it can be indexed a second time. isinstance rather than
    # cast: it checks the assumption instead of asserting it away.
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)

    assert calls[0]["follow_redirects"] is True
    assert "anlagen-copilot" in headers["User-Agent"]
