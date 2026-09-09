"""RAG copilot for industrial plant and machine documentation.

Ingests German manufacturer PDFs into pgvector and measures how well the pages
an answer would have to cite come back. No answer generation, and no second
ingestion strategy beyond the `Strategy` literal.
Manifest: data/raw/corpus.yaml — entry point: anlagen_copilot.cli.main.
"""
