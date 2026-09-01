import logging
from pathlib import Path

import ftfy
from openai import BadRequestError, OpenAI
from pgvector import Vector
from psycopg import Connection
from pypdf import PasswordType, PdfReader
from pypdf.errors import DependencyError, PdfReadError

from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.embeddings import embed
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)

# Above this size an excerpt is worth having. Deliberately set above the 428
# pages of siemens-g120c-kurz, which is indexed in full on purpose: the only
# document in the corpus larger than that (siemens-g120c-liste, 572) has an
# excerpt. The warning therefore only fires once a new manual of that size
# arrives unfiltered — today it stays silent.
_EXCERPT_HINT_PAGES = 500

# pypdf hands back cp1252 bytes as C1 control characters where it cannot resolve
# a font's encoding — 554 of them in one manual, invisible in a citation and
# noise in an embedding. `uncurl_quotes` stays off: flattening German „…" to
# "…" is typography, not repair, and would touch 9 unaffected chunks.
_TEXT_FIXES = ftfy.TextFixerConfig(uncurl_quotes=False)


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
            text = ftfy.fix_text(page.extract_text() or "", config=_TEXT_FIXES)
            pages.append((page_number, text))
    except (PdfReadError, DependencyError) as exc:
        raise DocumentError(f"{document.id}: PDF not readable") from exc

    return pages


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

    A rerun replaces the document rather than skipping it: the `DELETE` ahead of
    the loop clears what this strategy holds for this document, and the page
    loop writes it again. That is what lets a corrected extraction reach the
    index. Scoped by `strategy` as well as `document_id`, so the two strategies
    keep out of each other's way in the same table.

    `DELETE` rather than an upsert, because a page set can shrink: narrow
    `excerpt_pages` and an upsert leaves rows behind for pages that are no
    longer read.

    Writes but does not commit. The caller's transaction is what keeps the
    `DELETE` and the `INSERT`s together — a document that fails midway is left
    as it was, not emptied.

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

    strategy = get_settings().ingest_strategy

    conn.execute(
        """
        DELETE FROM chunks WHERE strategy = %s AND document_id = %s
        """,
        (strategy, document.id),
    )

    rejected = 0

    for page_number, text in usable:
        try:
            vector = embed(client, text)
        except BadRequestError as exc:
            # The API's own message names the reason and the measured length;
            # recomputing either here would only add a second, disagreeable
            # source of truth.
            logger.warning(
                "%s: page %d rejected (%d characters): %s", document.id, page_number, len(text), exc
            )
            rejected += 1
            continue

        conn.execute(
            """
            INSERT INTO chunks (strategy, document_id, page, content, embedding)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                strategy,
                document.id,
                page_number,
                text,
                # Vector() rather than the bare list: register_vector() registers a
                # dumper for Vector and numpy.ndarray, not for list, so a list is sent
                # as float8[]. This INSERT would survive that — pgvector defines an
                # assignment cast from double precision[] to vector, and an INSERT is
                # an assignment context. The same value next to an operator would not:
                # `embedding <=> %s` needs an implicit cast, and there is none.
                Vector(vector),
            ),
        )
        logger.debug("%s: embedded page %d (%d characters)", document.id, page_number, len(text))

    if rejected:
        logger.warning(
            "%s: %d of %d pages rejected by the embedding model",
            document.id,
            rejected,
            len(usable),
        )

    logger.info(
        "%s: embedded %d of %d pages",
        document.id,
        len(usable) - rejected,
        len(pages),
    )
