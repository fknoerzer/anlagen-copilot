import logging
from pathlib import Path

import tiktoken
from openai import BadRequestError, OpenAI
from psycopg import Connection
from pypdf import PasswordType, PdfReader
from pypdf.errors import DependencyError, PdfReadError

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)

# Above this size an excerpt is worth having. Deliberately set above the 428
# pages of siemens-g120c-kurz, which is indexed in full on purpose: the only
# document in the corpus larger than that (siemens-g120c-liste, 572) has an
# excerpt. The warning therefore only fires once a new manual of that size
# arrives unfiltered — today it stays silent.
_EXCERPT_HINT_PAGES = 500

_ENCODING = tiktoken.get_encoding("cl100k_base")


def extract_pages(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Reads a PDF page by page, returning (page number, text) for each page.

    When `excerpt_pages` is set only that range is read, both bounds inclusive.
    Page numbers stay those of the original PDF and are *not* renumbered from
    1: `chunks.page` is the citation the eval set checks against as well.
    Renumbering would shift every reference silently by the start offset and
    send readers to the wrong manual page.

    The slice happens before extraction because `PdfReader.pages` is lazy —
    `extract_text()` then only runs on the pages actually needed.

    Raises:
        DocumentError: When the file is unreadable, or will not open with an
            empty password. The pypdf branch deliberately wraps the extraction
            loop too: `extract_text()` can fail on a single damaged page, not
            just `PdfReader()`.
    """

    path: Path = raw_dir / document.filename

    try:
        reader = PdfReader(path)

        if document.encrypted:
            result = reader.decrypt("")

            if result == PasswordType.NOT_DECRYPTED:
                raise DocumentError(f"{document.id}: decryption with empty password failed")

        # Without an excerpt, the file's actual page count rather than
        # document.pages: where the manifest disagrees, nothing here should
        # truncate silently.
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
            text = page.extract_text() or ""
            pages.append((page_number, text))
    except (PdfReadError, DependencyError) as exc:
        raise DocumentError(f"{document.id}: PDF not readable") from exc

    return pages


def embed(client: OpenAI, text: str) -> list[float]:
    """Embeds one text and returns the vector.

    Catches nothing on purpose. How far a failure reaches is something only the
    caller can know: here a text is a text, and whether losing it is bearable
    is decided by the loop above.

    Raises:
        BadRequestError: When the model rejects the input — practically always
            the token limit on a dense table page. Concerns exactly this text,
            which is why the caller decides what it means: `ingest_document()`
            skips the page, `check_embedding_config()` has no page to skip and
            lets the run end.
        OpenAIError: Every other case (authentication, rate limit, connection).
            Those would hit every further call just the same and should end the
            run — which is why nobody catches them further up either.
    """
    response = client.embeddings.create(
        model=get_settings().embedding_model,
        input=text,
        dimensions=get_settings().embedding_dimensions,
    )
    return response.data[0].embedding


def check_embedding_config(client: OpenAI) -> None:
    """Verifies model, dimensions and API key with a single embedding call.

    Runs once before the ingestion loop, so a misconfiguration ends the run in a
    second instead of having to be inferred from a pattern of rejected pages.
    Deliberately goes through `embed()` rather than calling the API itself:
    whatever the ingestion sends later, the preflight has sent already, and the
    two cannot drift apart.

    Catches nothing. Every failure here concerns the whole run — a dimension the
    model will not take, an unknown model, a bad key — and none of them would
    look any different on the next document, so they are left to end it.
    """
    embed(client, "preflight")
    logger.info(
        "Embedding config verified: model '%s', %d dimensions",
        get_settings().embedding_model,
        get_settings().embedding_dimensions,
    )


def ingest_document(
    client: OpenAI,
    document: CorpusDocument,
    conn: Connection,
    raw_dir: Path,
) -> None:
    """Embeds one document page by page and writes the chunks to the database.

    One page is one chunk. That is a deliberate baseline for the naive
    strategy, not an oversight: the page is the unit the eval set cites and the
    unit an answer can send a reader to. Splitting along semantic boundaries is
    the job of the advanced strategy, and the `UNIQUE (strategy, document_id,
    page)` constraint would have to give way with it.

    Two kinds of page never reach the index, each counted in a warning instead
    of ending the document: pages without extractable text (scans, pure
    graphics) and pages the embedding model rejects — practically always the
    token limit on a dense table page.

    A rejection may be read as a statement about that one page because
    `check_embedding_config()` has already ruled out the alternative: a 400 that
    covers every page alike — a dimension the model will not take, an unknown
    model — has ended the run before the first page was ever read.

    Writes but does not commit. The caller owns the transaction, so a document
    that fails midway leaves no half-written index behind, and `ON CONFLICT DO
    NOTHING` makes a rerun a no-op rather than a source of duplicates.

    Raises:
        DocumentError: From `extract_pages()`, when the PDF is unreadable or
            will not open with an empty password. A rejected page is skipped;
            everything else propagates unwrapped and ends the run.
    """
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

    logger.info("%s: starting to embed %d pages", document.id, len(usable))

    rejected: list[tuple[int, int]] = []  # (page, tokens)

    for page_number, text in usable:
        try:
            vector = embed(client, text)
        except BadRequestError:
            rejected.append((page_number, len(_ENCODING.encode(text))))
            continue

        conn.execute(
            """
            INSERT INTO chunks (strategy, document_id, page, content, embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (get_settings().ingest_strategy, document.id, page_number, text, vector),
        )
        logger.debug("%s: embedded page %d (%d characters)", document.id, page_number, len(text))

    if rejected:
        logger.warning(
            "%s: %d of %d pages rejected by embedding model: %s",
            document.id,
            len(rejected),
            len(usable),
            rejected,
        )

    logger.info(
        "%s: embedded %d of %d pages",
        document.id,
        len(usable) - len(rejected),
        len(pages),
    )
