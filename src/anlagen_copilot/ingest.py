from pathlib import Path

from openai import OpenAI
from psycopg import Connection
from pypdf import PdfReader

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.settings import get_settings


def extract_pages(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Liest ein PDF Seite für Seite aus, gibt (Seitenzahl, Text) je Seite zurück.

    Ist `excerpt_pages` gesetzt, wird nur dieser Bereich gelesen — beide Grenzen
    einschließend. Die Seitenzahlen bleiben dabei die des Original-PDFs und
    zählen *nicht* ab 1 neu: `chunks.page` ist die Quellenangabe, gegen die auch
    das Eval-Set prüft. Eine Neunummerierung würde jeden Verweis still um den
    Startoffset verschieben und Leser auf die falsche Handbuchseite schicken.

    Der Schnitt passiert vor dem Auslesen, weil `PdfReader.pages` lazy ist —
    `extract_text()` läuft so nur auf den tatsächlich benötigten Seiten.
    """

    path: Path = raw_dir / document.filename

    reader = PdfReader(path)

    if document.encrypted:
        result = reader.decrypt("")

        if result == 0:
            raise ValueError(f"{document.id}: Entschlüsselung mit leerem Passwort fehlgeschlagen")

    # Ohne Auszug die tatsächliche Seitenzahl der Datei, nicht document.pages:
    # weicht das Manifest ab, soll das hier nichts stillschweigend abschneiden.
    first_page, last_page = document.excerpt_pages or (1, len(reader.pages))

    pages: list[tuple[int, str]] = []

    for page_number, page in enumerate(reader.pages[first_page - 1 : last_page], start=first_page):
        text = page.extract_text()
        pages.append((page_number, text))

    return pages


def embed(client: OpenAI, text: str) -> list[float]:
    response = client.embeddings.create(
        model=get_settings().embedding_model,
        input=text,
        dimensions=get_settings().embedding_dimensions,
    )
    return response.data[0].embedding


def ingest_document(
    client: OpenAI,
    document: CorpusDocument,
    conn: Connection,
    raw_dir: Path,
) -> None:
    pages = extract_pages(document, raw_dir)
    usable = [(page_number, text) for page_number, text in pages if text.strip()]
    for page_number, text in usable:
        vector = embed(client, text)
        conn.execute(
            """
            INSERT INTO chunks (strategy, document_id, page, content, embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (get_settings().ingest_strategy, document.id, page_number, text, vector),
        )
