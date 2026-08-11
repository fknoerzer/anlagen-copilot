import io
from pathlib import Path
from typing import BinaryIO

import httpx
from pypdf import PdfReader

from anlagen_copilot.corpus import CorpusDocument


def download_document(doc: CorpusDocument, raw_dir: Path) -> None:
    """Lädt doc.url herunter und speichert es unter raw_dir/doc.filename.

    Existiert die Zieldatei bereits, wird der Download übersprungen (kein
    erneuter Download bei jedem Lauf). Die Seitenzahl wird vor dem Schreiben
    geprüft, damit bei einem Mismatch keine fehlerhafte Datei auf der Platte
    landet (die ein künftiger Lauf sonst über den Existenz-Check stillschweigend
    übernehmen würde).

    Raises:
        httpx.HTTPStatusError: Bei 4xx/5xx-Antworten des Servers.
        ValueError: Wenn die heruntergeladene PDF nicht die im Manifest
            angegebene Seitenzahl hat (siehe check_pages).
    """
    target = raw_dir / doc.filename

    if target.is_file():
        return

    response = httpx.get(str(doc.url), timeout=30).raise_for_status()
    check_pages(doc.pages, io.BytesIO(response.content), label=doc.filename)
    target.write_bytes(response.content)


def check_pages(number_pages: int, source: Path | BinaryIO, *, label: str) -> None:
    """Prüft die Seitenzahl einer PDF gegen das Manifest.

    Fängt Fälle ab, in denen sich eine Herstellerausgabe geändert hat, ohne
    dass corpus.yaml aktualisiert wurde — sonst würden falsche Seitenzahlen
    unbemerkt in Quellenangaben landen. source kann sowohl ein Pfad zu einer
    bereits gespeicherten Datei als auch ein In-Memory-Stream (z. B. direkt
    aus einer Response) sein.

    Raises:
        ValueError: Wenn die tatsächliche Seitenzahl von number_pages abweicht.
    """
    reader = PdfReader(source)
    actual_pages = len(reader.pages)

    if actual_pages != number_pages:
        raise ValueError(
            f"{label}: erwartete {number_pages} Seiten laut Manifest, "
            f"PDF hat tatsächlich {actual_pages}"
        )
