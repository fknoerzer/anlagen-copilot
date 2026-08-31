import io
import logging
from pathlib import Path
from typing import BinaryIO

import httpx
from pypdf import PdfReader

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError

logger = logging.getLogger(__name__)


def download_document(doc: CorpusDocument, raw_dir: Path) -> None:
    """Downloads doc.url and stores it as raw_dir/doc.filename.

    If the target file already exists the download is skipped, so a rerun does
    not fetch everything again. The page count is checked before writing, so a
    mismatch never leaves a wrong file on disk — a later run would otherwise
    adopt it silently through that same existence check.

    Raises:
        DocumentError: On 4xx/5xx responses from the server, or when the
            downloaded PDF does not have the page count the manifest declares
            (see check_pages). Both concern exactly this document. Network
            errors (timeout, no DNS) propagate as httpx exceptions instead —
            they affect every further download just the same.
    """
    target = raw_dir / doc.filename

    if target.is_file():
        logger.debug("%s: already present, download skipped", doc.filename)
        return

    logger.info("%s: downloading from %s", doc.filename, doc.url)
    response = httpx.get(str(doc.url), timeout=30)
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
