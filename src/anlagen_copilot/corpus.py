"""Pydantic-Repräsentation von data/raw/corpus.yaml, dem Korpus-Manifest.

Single Source of Truth für Ingestion, Retrieval-Filter, Quellenangaben
und Provenance-Nachweis — siehe corpus.yaml selbst für den Zweck.
"""

from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PositiveInt, model_validator

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS_PATH = _PROJECT_ROOT / "data" / "raw" / "corpus.yaml"


class CorpusMeta(BaseModel):
    name: str
    language: str
    description: str
    raw_dir: str


class CorpusDocument(BaseModel):
    """Ein Dokument des Referenzkorpus, wie in data/raw/corpus.yaml deklariert.

    Dient als Single Source of Truth für Ingestion (Metadaten pro Chunk),
    Retrieval-Filter (doc_type, domain), Quellenangaben (title) und
    Provenance-Nachweis (url, edition, retrieved).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    filename: str
    title: str
    manufacturer: str
    doc_type: Literal[
        "betriebsanleitung",
        "tabellenwerk",
        "katalog",
        "kompaktanleitung",
        "listenhandbuch",
    ]
    domain: Literal["mechanik", "elektronik"]
    pages: PositiveInt = Field(
        description="Gesamtseitenzahl des Original-PDFs (nicht die indexierte Teilmenge)"
    )
    url: HttpUrl
    retrieved: date
    edition: str | None = None
    encrypted: bool = False
    excerpt_pages: tuple[int, int] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_excerpt_pages(self) -> Self:
        """Prüft einen Seitenauszug gegen den Gesamtumfang des Dokuments.

        Läuft nur, wenn `excerpt_pages` gesetzt ist. Ein fehlerhafter Bereich
        würde sonst zu falschen Quellenangaben führen.

        Raises:
            ValueError: Wenn Start < 1, Start >= Ende oder Ende > `pages`.
        """
        excerpt = self.excerpt_pages
        if excerpt is None:
            return self

        start, end = excerpt
        if start < 1:
            raise ValueError("excerpt_pages: Startseite muss >= 1 sein")
        if start >= end:
            raise ValueError(f"excerpt_pages: Start ({start}) muss kleiner als Ende ({end}) sein")
        if end > self.pages:
            raise ValueError(
                f"excerpt_pages: Ende ({end}) liegt hinter der letzten Seite ({self.pages})"
            )
        return self


class CrossReference(BaseModel):
    question_pattern: str
    documents: list[str]


class Corpus(BaseModel):
    corpus: CorpusMeta
    documents: list[CorpusDocument]
    cross_references: list[CrossReference]


def load_corpus(path: Path = DEFAULT_CORPUS_PATH) -> Corpus:
    """Lädt und validiert das Korpus-Manifest.

    Args:
        path: Pfad zur Manifest-Datei. Default ist data/raw/corpus.yaml,
            aufgelöst relativ zum Projekt-Root (nicht zum Arbeitsverzeichnis).

    Returns:
        Corpus: Das validierte Manifest.

    Raises:
        FileNotFoundError: Wenn die Datei nicht existiert.
        ValidationError: Wenn das Manifest strukturell fehlerhaft ist.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Korpus-Manifest nicht gefunden: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Corpus.model_validate(raw)
