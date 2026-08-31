"""Pydantic representation of data/eval_set.yaml, the RAG eval manifest.

Validates structure and consistency of the eval questions, among other things
against corpus.yaml (load_corpus), so a mistyped document_id cannot slip
through unnoticed.
"""

import logging
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt, model_validator

from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.paths import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_EVALSET_PATH = DATA_DIR / "eval_set.yaml"


class ExpectedSource(BaseModel):
    """One page a question must be answerable from — the retrieval ground truth.

    `page` is a page number of the original PDF and therefore comparable to
    `chunks.page` directly. That holds for excerpted documents too: ingestion
    deliberately does not renumber an excerpt from 1, otherwise every value
    here would point at the wrong manual page.

    `EvalSet.check_document_id()` validates `document_id` against corpus.yaml;
    `page` gets no such check, because this is the page an answer is expected
    on, not a claim about what was indexed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page: PositiveInt


class EvalQuestion(BaseModel):
    """One eval question from data/eval_set.yaml with its expected sources and facts.

    Ground truth for scoring the RAG pipeline: expected_sources for the
    retrieval comparison, expected_facts for the answer comparison.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    category: Literal["lookup", "table", "diagram", "multi-hop", "unanswerable"]
    question: str
    expected_sources: list[ExpectedSource]
    expected_facts: list[str]
    notes: str | None = None

    @model_validator(mode="after")
    def check_unanswerable_consistency(self) -> Self:
        """Enforces: unanswerable questions empty, every other one filled.

        Without this check an unanswerable question could carry sources by
        accident (which are then never reachable), or an answerable one could
        end up with no ground truth at all.

        Raises:
            ValueError: On an inconsistent combination of category and content.
        """
        is_unanswerable = self.category == "unanswerable"
        has_content = bool(self.expected_sources or self.expected_facts)

        if is_unanswerable and has_content:
            raise ValueError(f"{self.id}: unanswerable question must not have sources or facts")
        if not is_unanswerable and not has_content:
            raise ValueError(f"{self.id}: answerable question needs sources and facts")
        return self


class EvalSet(BaseModel):
    """The complete eval set, checked for consistency against corpus.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: list[EvalQuestion]

    @model_validator(mode="after")
    def check_document_id(self) -> Self:
        """Checks that every referenced document_id exists in corpus.yaml.

        Runs once for the whole set rather than per question, so corpus.yaml is
        not loaded repeatedly. Catches the typos that would otherwise run into
        the void unnoticed until the retrieval comparison.

        Raises:
            ValueError: When a document_id does not occur in the manifest.
        """
        corpus = load_corpus()

        corpus_doc_ids = {doc.id for doc in corpus.documents}

        for question in self.questions:
            for source in question.expected_sources:
                if source.document_id not in corpus_doc_ids:
                    raise ValueError(
                        f"{question.id}: document_id '{source.document_id}' "
                        "not found in corpus.yaml"
                    )

        return self


def load_eval(path: Path = DEFAULT_EVALSET_PATH) -> EvalSet:
    """Loads and validates the eval set manifest.

    Args:
        path: Path to the manifest file. Defaults to data/eval_set.yaml,
            resolved against the project root, not the working directory.

    Returns:
        EvalSet: The validated eval set.

    Raises:
        FileNotFoundError: When the file does not exist.
        ValidationError: When the manifest is structurally invalid, or
            inconsistent with corpus.yaml, e.g. an unknown document_id.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Eval set manifest not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    eval_set = EvalSet.model_validate(raw)
    logger.info("Eval set loaded: %d questions from %s", len(eval_set.questions), path)
    return eval_set
