from openai import OpenAI

from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.db import get_connection
from anlagen_copilot.ingest import ingest_document
from anlagen_copilot.scripts.download_corpus import download_document
from anlagen_copilot.settings import get_settings


def main() -> None:
    corpus = load_corpus()
    raw_path = corpus.corpus.raw_dir
    client = OpenAI(api_key=get_settings().openai_api_key.get_secret_value())
    with get_connection() as conn:
        for doc in corpus.documents:
            download_document(doc, raw_path)
            ingest_document(client, doc, conn, raw_path)
