import logging
from pathlib import Path

from openai import BadRequestError, OpenAI
from psycopg import Connection
from pypdf import PdfReader
from pypdf.errors import DependencyError, PdfReadError

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)

# Ab dieser Größe lohnt ein Auszug. Bewusst über den 428 Seiten von
# siemens-g120c-kurz angesetzt, das absichtlich vollständig indexiert wird:
# Das einzige Dokument im Korpus darüber (siemens-g120c-liste, 572) hat einen
# Auszug. Die Warnung schlägt also erst an, wenn ein neues Handbuch dieser
# Größenordnung ungefiltert dazukommt — heute schweigt sie.
_EXCERPT_HINT_PAGES = 500


def extract_pages(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Liest ein PDF Seite für Seite aus, gibt (Seitenzahl, Text) je Seite zurück.

    Ist `excerpt_pages` gesetzt, wird nur dieser Bereich gelesen — beide Grenzen
    einschließend. Die Seitenzahlen bleiben dabei die des Original-PDFs und
    zählen *nicht* ab 1 neu: `chunks.page` ist die Quellenangabe, gegen die auch
    das Eval-Set prüft. Eine Neunummerierung würde jeden Verweis still um den
    Startoffset verschieben und Leser auf die falsche Handbuchseite schicken.

    Der Schnitt passiert vor dem Auslesen, weil `PdfReader.pages` lazy ist —
    `extract_text()` läuft so nur auf den tatsächlich benötigten Seiten.

    Raises:
        DocumentError: Wenn die Datei nicht lesbar ist oder sich nicht mit
            leerem Passwort öffnen lässt. Der pypdf-Zweig umschließt bewusst
            auch die Ausleseschleife: `extract_text()` kann bei einer einzelnen
            beschädigten Seite ebenfalls scheitern, nicht nur `PdfReader()`.
    """

    path: Path = raw_dir / document.filename

    try:
        reader = PdfReader(path)

        if document.encrypted:
            result = reader.decrypt("")

            if result == 0:
                raise DocumentError(f"{document.id}: decryption with empty password failed")

        # Ohne Auszug die tatsächliche Seitenzahl der Datei, nicht document.pages:
        # weicht das Manifest ab, soll das hier nichts stillschweigend abschneiden.
        first_page, last_page = document.excerpt_pages or (1, len(reader.pages))

        logger.debug(
            "%s: reading pages %d-%d of %d", document.id, first_page, last_page, len(reader.pages)
        )

        if document.excerpt_pages is None and len(reader.pages) > _EXCERPT_HINT_PAGES:
            logger.warning(
                "%s: ingesting all %d pages, no excerpt_pages set",
                document.id,
                len(reader.pages),
            )

        pages: list[tuple[int, str]] = []

        for page_number, page in enumerate(
            reader.pages[first_page - 1 : last_page], start=first_page
        ):
            text = page.extract_text()
            pages.append((page_number, text))
    except (PdfReadError, DependencyError) as exc:
        raise DocumentError(f"{document.id}: PDF not readable") from exc

    return pages


def embed(client: OpenAI, text: str) -> list[float]:
    """Bettet einen Text ein und gibt den Vektor zurück.

    Raises:
        DocumentError: Wenn das Modell den Text ablehnt — praktisch immer die
            Token-Grenze bei einer dichten Tabellenseite. Andere OpenAI-Fehler
            (Authentifizierung, Rate-Limit, Verbindung) fliegen durch: sie
            träfen jeden weiteren Aufruf genauso und sollen den Lauf beenden.
    """
    try:
        response = client.embeddings.create(
            model=get_settings().embedding_model,
            input=text,
            dimensions=get_settings().embedding_dimensions,
        )
    except BadRequestError as exc:
        raise DocumentError(f"page rejected by embedding model ({len(text)} characters)") from exc
    return response.data[0].embedding


def ingest_document(
    client: OpenAI,
    document: CorpusDocument,
    conn: Connection,
    raw_dir: Path,
) -> None:
    pages = extract_pages(document, raw_dir)
    usable = [(page_number, text) for page_number, text in pages if text.strip()]
    skipped = len(pages) - len(usable)
    if skipped:
        logger.warning(
            "%s: skipped %d of %d pages without extractable text",
            document.id,
            skipped,
            len(pages),
        )

    logger.info("%s: embedding %d pages", document.id, len(usable))

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
        logger.debug("%s: embedded page %d (%d characters)", document.id, page_number, len(text))
