"""Pydantic representation of data/raw/corpus.yaml, the corpus manifest.

Single source of truth for ingestion, retrieval filters, citations and
provenance — see corpus.yaml itself for the rationale.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PositiveInt,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS_PATH = _PROJECT_ROOT / "data" / "raw" / "corpus.yaml"


class CorpusMeta(BaseModel):
    """The `corpus:` header of data/raw/corpus.yaml — the collection itself.

    Describes the collection, not any single document. `raw_dir` is the only
    field with behaviour attached: the validator below resolves it against the
    project root, so callers can rely on getting an absolute path.
    """

    name: str
    language: str
    description: str
    raw_dir: Path

    @field_validator("raw_dir")
    @classmethod
    def resolve_raw_dir(cls, p: Path) -> Path:
        """Resolves raw_dir against the project root when given as relative.

        Without this, raw_dir would depend on the working directory at call
        time instead of on where the manifest itself sits — running main() from
        another directory would read from and write to the wrong place.
        """
        return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


class CorpusDocument(BaseModel):
    """One document of the reference corpus, as declared in data/raw/corpus.yaml.

    Single source of truth for ingestion (per-chunk metadata), retrieval
    filters (doc_type, domain), citations (title) and provenance (url, edition,
    retrieved).
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
        description="Total page count of the original PDF, not the indexed subset"
    )
    url: HttpUrl
    retrieved: date
    edition: str | None = None
    encrypted: bool = False
    excerpt_pages: tuple[int, int] | None = Field(
        default=None,
        description=(
            "Only this page range is indexed, both bounds inclusive: "
            "(453, 548) = 96 pages. None = the whole document. Numbering is "
            "that of the original PDF and stays so in chunks.page."
        ),
    )
    notes: str | None = None

    @model_validator(mode="after")
    def check_excerpt_pages(self) -> Self:
        """Checks a page excerpt against the document's total extent.

        Only runs when `excerpt_pages` is set. A faulty range would otherwise
        lead to wrong citations.

        Raises:
            ValueError: When start < 1, start >= end, or end > `pages`.
        """
        excerpt = self.excerpt_pages
        if excerpt is None:
            return self

        start, end = excerpt
        if start < 1:
            raise ValueError("excerpt_pages: first page must be >= 1")
        if start >= end:
            raise ValueError(f"excerpt_pages: start ({start}) must be less than end ({end})")
        if end > self.pages:
            raise ValueError(f"excerpt_pages: end ({end}) is past the last page ({self.pages})")
        return self


class CrossReference(BaseModel):
    """A question shape that no single document can answer on its own.

    Records the corpus's deliberate overlaps — picking an oil needs the gearbox
    manual *and* the lubricant table, a fault code needs the parameter list
    *and* the motor manual. Documentation of intent only: no code reads this
    field, it justifies the multi-hop questions in the eval set.
    """

    question_pattern: str
    documents: list[str]


class Corpus(BaseModel):
    """The whole manifest — root model that `load_corpus()` validates against.

    The `corpus.corpus.raw_dir` nesting is intentional: the YAML separates
    header data (`corpus:`) from the document list, and this model mirrors the
    file rather than flattening it on load.
    """

    corpus: CorpusMeta
    documents: list[CorpusDocument]
    cross_references: list[CrossReference]


def load_corpus(path: Path = DEFAULT_CORPUS_PATH) -> Corpus:
    """Loads and validates the corpus manifest.

    Args:
        path: Path to the manifest file. Defaults to data/raw/corpus.yaml,
            resolved against the project root, not the working directory.

    Returns:
        Corpus: The validated manifest.

    Raises:
        FileNotFoundError: When the file does not exist.
        ValidationError: When the manifest is structurally invalid.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Corpus manifest not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    corpus = Corpus.model_validate(raw)
    logger.info("Corpus manifest loaded: %d documents from %s", len(corpus.documents), path)
    return corpus
