import logging

from openai import OpenAI

from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.db import get_connection
from anlagen_copilot.embeddings import check_embedding_config
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.ingest import ingest_document
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.scripts.download_corpus import download_document
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Runs the ingestion end to end: manifest, download, embedding, database.

    Entry point for both `anlagen-copilot` and `python -m anlagen_copilot`.

    The embedding configuration is verified before anything is downloaded or
    written, so a wrong model, dimension or key ends the run in a second rather
    than after the first manual has been fetched over the wire.

    One transaction per document rather than one per run, so an INFO line means
    the same thing as the database state. The boundary does more than tidy the
    log: `ingest_document()` deletes the document's chunks before writing them
    again, and only this transaction makes the two halves inseparable. Abort in
    between and the document stands as it was; without it, a failed rerun would
    leave it empty.
    `download_document()` sits outside the transaction deliberately: it does no
    database work, but would hold one open across a 30-second download.

    `DocumentError` is the only failure this loop absorbs — it carries the
    claim "affects exactly one document", so that document is skipped and the
    run goes on. Anything else (a bad API key, a connection failure) would hit
    every remaining document just the same and is left to end the run.

    Raises:
        SystemExit: Code 1 if any document was skipped, so that a partial run
            is not mistaken for a complete one by CI or by a later step.
    """
    setup_logging()
    corpus = load_corpus()
    raw_path = corpus.corpus.raw_dir
    logger.info(
        "Ingestion started: %d documents, strategy '%s'",
        len(corpus.documents),
        get_settings().ingest_strategy,
    )
    client = OpenAI(api_key=get_settings().openai_api_key.get_secret_value())
    check_embedding_config(client)
    skipped_documents = []
    with get_connection() as conn:
        for doc in corpus.documents:
            try:
                download_document(doc, raw_path)
                with conn.transaction():
                    ingest_document(client, doc, conn, raw_path)
            except DocumentError:
                logger.exception("%s: skipped", doc.id)
                skipped_documents.append(doc.id)
    logger.info(
        "Ingestion finished: %d documents processed",
        len(corpus.documents) - len(skipped_documents),
    )
    if skipped_documents:
        logger.warning(
            "%d documents skipped: %s", len(skipped_documents), ", ".join(skipped_documents)
        )
        raise SystemExit(1)
