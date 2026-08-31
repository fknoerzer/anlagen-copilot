import io
import logging
from importlib.metadata import version
from pathlib import Path
from typing import BinaryIO

import httpx
from pypdf import PdfReader

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError

logger = logging.getLogger(__name__)

# A library's default agent ("python-httpx/0.28.1") is a common reason for a 403
# on manufacturer sites, and the contact URL lets whoever finds these requests in
# a server log see where they come from. The version comes from the package
# metadata rather than being written out, so it cannot drift from pyproject.toml.
_HTTP_HEADERS = {
    "User-Agent": (
        f"anlagen-copilot/{version('anlagen-copilot')} "
        "(+https://github.com/fknoerzer/anlagen-copilot)"
    )
}


def download_document(doc: CorpusDocument, raw_dir: Path) -> None:
    """Downloads doc.url and stores it as raw_dir/doc.filename.

    If the target file already exists the download is skipped, so a rerun does
    not fetch everything again. The page count is checked before writing, so a
    mismatch never leaves a wrong file on disk — a later run would otherwise
    adopt it silently through that same existence check.

    Redirects are followed, so the bytes may well come from a host other than
    the one in the manifest. `doc.url` stays the provenance record either way:
    it is the address the manufacturer publishes, not necessarily the CDN that
    ends up serving the file.

    Raises:
        DocumentError: On 4xx/5xx responses from the server, on a redirect
            loop, and when the downloaded PDF does not have the page count the
            manifest declares (see check_pages). All three concern exactly this
            document. Network errors (timeout, no DNS) propagate as httpx
            exceptions instead — they affect every further download just the
            same. The line is drawn by reach, not by exception family:
            TooManyRedirects and ConnectError are both httpx RequestErrors, yet
            only the first is a property of this one URL.
    """
    target = raw_dir / doc.filename

    if target.is_file():
        logger.debug("%s: already present, download skipped", doc.filename)
        return

    logger.info("%s: downloading from %s", doc.filename, doc.url)

    # httpx does not follow redirects on its own, unlike requests — and vendor
    # download links routinely point at a CDN. Only TooManyRedirects is caught
    # here: it is a RequestError, not an HTTPStatusError, so it would otherwise
    # slip past the handler below and end the whole run over one bad URL.
    try:
        response = httpx.get(
            str(doc.url),
            timeout=30,
            follow_redirects=True,
            headers=_HTTP_HEADERS,
        )
    except httpx.TooManyRedirects as exc:
        raise DocumentError(f"{doc.filename}: redirect loop at {doc.url}") from exc

    if response.history:
        logger.info(
            "%s: %d redirect(s), final URL %s",
            doc.filename,
            len(response.history),
            response.url,
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DocumentError(f"{doc.filename}: server responded {response.status_code}") from exc

    check_pages(doc.pages, io.BytesIO(response.content), label=doc.filename)
    target.write_bytes(response.content)
    logger.info("%s: saved %.1f MB", doc.filename, len(response.content) / 1_048_576)


def check_pages(number_pages: int, source: Path | BinaryIO, *, label: str) -> None:
    """Checks a PDF's page count against the manifest.

    Catches the cases where a manufacturer edition changed without corpus.yaml
    being updated — wrong page numbers would otherwise end up in citations
    unnoticed. source may be a path to an already stored file just as well as
    an in-memory stream, e.g. straight from a response.

    Raises:
        DocumentError: When the actual page count differs from number_pages.
    """
    reader = PdfReader(source)
    actual_pages = len(reader.pages)

    if actual_pages != number_pages:
        raise DocumentError(
            f"{label}: expected {number_pages} pages per manifest, PDF actually has {actual_pages}"
        )
