from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.scripts.download_corpus import download_document


def main() -> None:
    corpus = load_corpus()
    for doc in corpus.documents:
        download_document(doc, corpus.corpus.raw_dir)
