import logging

from openai import OpenAI

from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.db import get_connection
from anlagen_copilot.errors import DocumentError
from anlagen_copilot.ingest import ingest_document
from anlagen_copilot.logging_setup import setup_logging
from anlagen_copilot.scripts.download_corpus import download_document
from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    corpus = load_corpus()
    raw_path = corpus.corpus.raw_dir
    logger.info(
        "Ingestion started: %d documents, strategy '%s'",
        len(corpus.documents),
        get_settings().ingest_strategy,
    )
    client = OpenAI(api_key=get_settings().openai_api_key.get_secret_value())
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
