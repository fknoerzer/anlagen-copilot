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
    """Lädt doc.url herunter und speichert es unter raw_dir/doc.filename.

    Existiert die Zieldatei bereits, wird der Download übersprungen (kein
    erneuter Download bei jedem Lauf). Die Seitenzahl wird vor dem Schreiben
    geprüft, damit bei einem Mismatch keine fehlerhafte Datei auf der Platte
    landet (die ein künftiger Lauf sonst über den Existenz-Check stillschweigend
    übernehmen würde).

    Raises:
        DocumentError: Bei 4xx/5xx-Antworten des Servers, oder wenn die
            heruntergeladene PDF nicht die im Manifest angegebene Seitenzahl
            hat (siehe check_pages). Beides betrifft genau dieses Dokument.
            Netzfehler (Timeout, kein DNS) fliegen dagegen als httpx-Exception
            durch — sie betreffen jeden weiteren Download ebenso.
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
    """Prüft die Seitenzahl einer PDF gegen das Manifest.

    Fängt Fälle ab, in denen sich eine Herstellerausgabe geändert hat, ohne
    dass corpus.yaml aktualisiert wurde — sonst würden falsche Seitenzahlen
    unbemerkt in Quellenangaben landen. source kann sowohl ein Pfad zu einer
    bereits gespeicherten Datei als auch ein In-Memory-Stream (z. B. direkt
    aus einer Response) sein.

    Raises:
        DocumentError: Wenn die tatsächliche Seitenzahl von number_pages abweicht.
    """
    reader = PdfReader(source)
    actual_pages = len(reader.pages)

    if actual_pages != number_pages:
        raise DocumentError(
            f"{label}: expected {number_pages} pages per manifest, PDF actually has {actual_pages}"
        )
