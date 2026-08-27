"""Pydantic-Repräsentation von data/eval_set.yaml, dem RAG-Eval-Manifest.

Prüft Struktur und Konsistenz der Eval-Fragen, u. a. gegen corpus.yaml
(load_corpus), damit document_id-Tippfehler nicht unbemerkt bleiben.
"""

import logging
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt, model_validator

from anlagen_copilot.corpus import load_corpus

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVALSET_PATH = _PROJECT_ROOT / "data" / "eval_set.yaml"


class ExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page: PositiveInt


class EvalQuestion(BaseModel):
    """Eine Eval-Frage aus data/eval_set.yaml mit erwarteten Quellen/Fakten.

    Dient als Ground Truth zur Bewertung der RAG-Pipeline: expected_sources
    für den Retrieval-Vergleich, expected_facts für den Antwort-Vergleich.
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
        """Erzwingt: unanswerable-Fragen leer, alle anderen befüllt.

        Ohne diese Prüfung könnte eine unanswerable-Frage versehentlich
        Quellen tragen (die dann nie erreichbar sind) oder eine
        beantwortbare Frage ganz ohne Ground Truth bleiben.

        Raises:
            ValueError: bei inkonsistenter Kombination aus category und Inhalt.
        """
        is_unanswerable = self.category == "unanswerable"
        has_content = bool(self.expected_sources or self.expected_facts)

        if is_unanswerable and has_content:
            raise ValueError(f"{self.id}: unanswerable question must not have sources or facts")
        if not is_unanswerable and not has_content:
            raise ValueError(f"{self.id}: answerable question needs sources and facts")
        return self


class EvalSet(BaseModel):
    """Das vollständige Eval-Set, mit Konsistenzprüfung gegen corpus.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: list[EvalQuestion]

    @model_validator(mode="after")
    def check_document_id(self) -> Self:
        """Prüft, dass jede referenzierte document_id in corpus.yaml existiert.

        Läuft einmal für das gesamte Set (nicht pro Frage), damit corpus.yaml
        nicht mehrfach geladen wird. Fängt Tippfehler, die sonst erst beim
        Retrieval-Vergleich unbemerkt ins Leere liefen.

        Raises:
            ValueError: wenn eine document_id nicht im Korpus-Manifest vorkommt.
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
    """Lädt und validiert das Eval-Set-Manifest.

    Args:
        path: Pfad zur Manifest-Datei. Default ist data/eval_set.yaml,
            aufgelöst relativ zum Projekt-Root (nicht zum Arbeitsverzeichnis).

    Returns:
        EvalSet: Das validierte Eval-Set.

    Raises:
        FileNotFoundError: Wenn die Datei nicht existiert.
        ValidationError: Wenn das Manifest strukturell fehlerhaft ist oder
            gegen corpus.yaml inkonsistent ist (z. B. unbekannte document_id).
    """
    if not path.is_file():
        raise FileNotFoundError(f"Eval set manifest not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    eval_set = EvalSet.model_validate(raw)
    logger.info("Eval set loaded: %d questions from %s", len(eval_set.questions), path)
    return eval_set
