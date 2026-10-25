"""PDF in, embedded chunks in the `chunks` table out.

The write side of the pipeline, the counterpart to `retrieval.py`.
`extract_document()` reads a document, with pypdf or Docling by strategy, and
`ingest_document()` embeds and stores it, one chunk per page.
"""

import logging
import re
from collections import Counter
from functools import cache
from pathlib import Path

import ftfy
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import DEFAULT_PAGE_RANGE
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError
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

# 0.85 sits in the gap measured across the corpus: every running header or footer
# turns up on at least 89 % of its document's pages, no content line on more than
# 82 % — the table heads in sew-schmierstoffe, "Reaktion: KEINE" in the fault list.
# The gap is seven points wide and rests on one 34-page document.
_BOILERPLATE_MIN_RATIO = 0.85

# Below ten pages, "85 % of them" means eight or nine pages, a count a single
# chapter title reaches by chance. The smallest document in the corpus has 34.
_BOILERPLATE_MIN_PAGES = 10

# For `text_encoding_defect: cp1252_as_macroman`: the font hands out cp1252
# bytes that pypdfium2 reads as MacRoman, so "müssen" arrives as "m¸ssen". Only
# characters of German technical text are mapped back, not the whole page: the
# same pages carry text in other fonts that arrives correctly, and "—" or "→"
# re-encoded would turn into "Ñ" and worse. On ten pages of the project planning
# catalogue the share of words also found by pypdf rose from 61-87 % to 82-94 %.
_CP1252_AS_MACROMAN = str.maketrans(
    {char.encode("cp1252").decode("mac_roman"): char for char in "äöüÄÖÜß°•®"}
)

_REPLACEMENT_CHARACTER = "�"


@cache
def _converter(*, pdfium: bool) -> DocumentConverter:
    """Build the Docling converter once per process and backend and hand out the same one.

    The point is one place for the pipeline options, and one seam the tests can
    replace. That the models then load once per run instead of once per
    document saves little: about eight seconds each, some fifty for the six
    manuals, against an hour or more of conversion.

    OCR stays on, although it is what makes Docling slow: on two probed pages a
    conversion took 6-8 s with it and 1.4-2.8 s without. The text layer misses
    what a page shows only as an image, such as the EFF class marks in the
    project planning catalogue (q-034), and OCR reads them. Its noise is the
    price: a QR code came back as a stray character.

    `pdfium` swaps Docling's default PDF backend for pypdfium2, for documents
    with a known text encoding defect. The default backend turns characters of
    a font it cannot decode into U+FFFD, a loss no repair can undo; pypdfium2
    gives them back as other characters, which `_CP1252_AS_MACROMAN` maps home.
    """
    options = PdfPipelineOptions(do_ocr=True)
    pdf_format = (
        PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend)
        if pdfium
        else PdfFormatOption(pipeline_options=options)
    )
    return DocumentConverter(format_options={InputFormat.PDF: pdf_format})


def extract_pages_docling(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Read a PDF page by page with Docling, returning (page number, Markdown) for each page.

    The excerpt goes to `convert()` as `page_range` instead of being cut out
    afterwards. Unlike pypdf, Docling runs its layout and table models on every
    page it is given before returning, so a slice afterwards would still pay
    for the whole manual. The keys of `doc.pages` are the page numbers of the
    original PDF, so they become `chunks.page` as they are, without counting.

    `traverse_pictures=True` keeps the text Docling finds inside a picture. The
    nameplates and exploded drawings in the SEW manuals are vector graphics
    with real text; without the option the Markdown export replaces each of them
    with an image placeholder and drops that text without an error.

    The other export options keep Markdown syntax out of what gets embedded:
    no image placeholder, since the picture's text is now in its place; no HTML
    escaping, which turns "<" into "&lt;"; no escaped underscores; and tables
    without the padding that aligns their columns, which only costs tokens. The
    placeholder for an undecoded formula stays: it tells the answering model
    that something is missing where the page announces a formula.

    A partial conversion fails like a failed one. `convert()` raises only for a
    failure and returns `PARTIAL_SUCCESS` as a normal result, so pages it could
    not read would come back empty and be skipped as pages without text.

    A document with a `text_encoding_defect` is read through pypdfium2 and
    repaired page by page. A U+FFFD left after the repair means the defect is
    not the one declared, and the document fails rather than going into the
    index with words the search cannot match. Elsewhere a U+FFFD is logged:
    the default backend loses characters of fonts it cannot decode, and the
    count shows where a document would need a declared defect of its own.

    Raises:
        DocumentError: When Docling cannot convert the file, or converts only
            part of it, or characters remain lost after the declared repair.
    """
    path: Path = raw_dir / document.filename
    defect = document.text_encoding_defect

    try:
        result = _converter(pdfium=defect is not None).convert(
            path, page_range=document.excerpt_pages or DEFAULT_PAGE_RANGE
        )
    except ConversionError as exc:
        raise DocumentError(f"{document.id}: PDF not convertible") from exc

    if result.status != ConversionStatus.SUCCESS:
        errors = "; ".join(error.error_message for error in result.errors)
        raise DocumentError(f"{document.id}: conversion ended with {result.status.value}: {errors}")

    doc = result.document
    pages: list[tuple[int, str]] = []
    for page_number in sorted(doc.pages):
        text = doc.export_to_markdown(
            page_no=page_number,
            traverse_pictures=True,
            image_placeholder="",
            escape_html=False,
            escape_underscores=False,
            compact_tables=True,
        )
        if defect == "cp1252_as_macroman":
            text = text.translate(_CP1252_AS_MACROMAN)

        lost = text.count(_REPLACEMENT_CHARACTER)
        if lost and defect is not None:
            raise DocumentError(
                f"{document.id}: page {page_number} still has {lost} lost characters "
                f"after the {defect} repair"
            )
        if lost:
            logger.warning(
                "%s: page %d has %d characters lost to a font encoding",
                document.id,
                page_number,
                lost,
            )

        pages.append((page_number, ftfy.fix_text(text, config=_TEXT_FIXES)))
    return pages


def extract_pages(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Read a PDF page by page, returning (page number, text) for each page.

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


def _normalize_line(line: str) -> str:
    """Reduce a line to the form a running header or footer shares across pages.

    Whitespace is collapsed first, because pypdf often leaves it trailing. Digits
    then become `#`, so "Seite 3/34" and "Seite 4/34" count as one line. Finally a
    page number at either end goes, so the even and odd variants of a header, with
    the number once on the left and once on the right, count as one as well.

    The trailing pattern takes whitespace only, never dots: allowing dots there
    would eat the ".." of "SPIROPLAN® W.." on the pages that carry a number after
    it, and split that header of sew-getriebe-ba into two variants again.

    A form without a letter comes back empty. Numbers, decimals, ranges and
    references share no text a header could carry, but they are table values:
    "-20 +40" stands on 62 % of the pages of sew-schmierstoffe, "[17]" on 28 % of
    sew-motoren-drn.
    """
    line = " ".join(line.split())
    line = re.sub(r"\d+", "#", line)
    line = re.sub(r"^#\s*|\s*#$", "", line)
    return line if any(ch.isalpha() for ch in line) else ""


def strip_boilerplate(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Remove the lines that repeat on nearly every page of one document.

    A running header or footer sits in every page's embedding as a constant share
    and pulls all similarities of a document into one narrow band. A line counts
    as boilerplate when its normalized form appears on at least
    `_BOILERPLATE_MIN_RATIO` of the pages. It is counted once per page, so a table
    repeating a row cannot push itself over the threshold.

    Frequency decides, position does not: pypdf returns the content stream's
    order, not the visual one, and the header of sew-getriebe-ba lands among the
    first or last three lines on only 6 of the 229 pages that carry it.

    The normalized form decides, the original line is what is kept or dropped, so
    the index keeps its real page and part numbers. Lines that normalize to
    nothing are never counted: blank lines, and lines without a letter. That
    leaves bare page and document numbers in place, but also the table values
    pypdf puts on lines of their own, which matter more.

    Returns:
        The pages in their original order and numbering; unchanged when the
        document has fewer than `_BOILERPLATE_MIN_PAGES` pages.
    """
    if len(pages) < _BOILERPLATE_MIN_PAGES:
        return pages

    counts: Counter[str] = Counter()
    for _, text in pages:
        counts.update({norm for line in text.split("\n") if (norm := _normalize_line(line))})

    boilerplate = {
        norm for norm, seen in counts.items() if seen / len(pages) >= _BOILERPLATE_MIN_RATIO
    }

    stripped: list[tuple[int, str]] = []
    for page_number, text in pages:
        kept = [line for line in text.split("\n") if _normalize_line(line) not in boilerplate]
        stripped.append((page_number, "\n".join(kept)))
    return stripped


def extract_document(document: CorpusDocument, raw_dir: Path) -> list[tuple[int, str]]:
    """Read a document with the extractor of the configured strategy and strip its boilerplate.

    The read half of the ingestion, kept apart from `ingest_document()` so the
    caller can run it outside the database transaction: Docling takes minutes
    per manual, and nothing it does touches the database.

    Raises:
        DocumentError: From `extract_pages()` or `extract_pages_docling()`, when
            the PDF cannot be read, or Docling converts only part of it.
    """
    extract = (
        extract_pages_docling if get_settings().ingest_strategy == "advanced" else extract_pages
    )
    return strip_boilerplate(extract(document, raw_dir))


def ingest_document(
    client: OpenAI,
    document: CorpusDocument,
    conn: Connection,
    pages: list[tuple[int, str]],
) -> int:
    """Embed the extracted pages of one document and write them to the database as chunks.

    One page is one chunk, under both strategies for now. That is a deliberate
    baseline, not an oversight: the page is the unit the eval set cites and the
    unit an answer can send a reader to. The advanced strategy changes only the
    extraction so far, so that its effect can be measured alone; splitting
    pages would need the `UNIQUE (strategy, document_id, page)` constraint to
    give way.

    Two kinds of page never reach the index: pages without extractable text
    (scans and pure graphics under pypdf, which has no OCR; under Docling,
    whatever its OCR cannot read either) and pages the embedding model rejects
    — practically always the token limit on a dense table page. Either is a
    warning while something survives and a `DocumentError` once nothing does,
    with a message per cause, since a better extraction and a smaller chunk are
    different repairs.

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

    Returns:
        The number of pages the embedding model rejected; zero when every
        extractable page reached the index. Pages without text stay out of the
        count — they read the same on every run, a rejection depends on the
        strategy. What the loss means for the run is `main()`'s call.

    Raises:
        DocumentError: When no page has extractable text or every page is
            rejected. Everything else propagates unwrapped and ends the run.
    """
    usable = [(page_number, text) for page_number, text in pages if text.strip()]
    skipped = len(pages) - len(usable)
    if skipped:
        logger.warning(
            "%s: skipped %d of %d pages without extractable text",
            document.id,
            skipped,
            len(pages),
        )

    if not usable:
        raise DocumentError(f"{document.id}: no page with extractable text")

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

    if rejected == len(usable):
        raise DocumentError(f"{document.id}: all {rejected} pages rejected by the embedding model")

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

    return rejected
