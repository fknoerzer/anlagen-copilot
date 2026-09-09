"""Embedding calls against the OpenAI API.

Shared by both directions deliberately: the ingestion embeds pages, the
retrieval embeds questions, and the two must land in the same coordinate
system. Model and dimension come from the settings in exactly one place, so
a query cannot silently be measured against differently built vectors.
"""

import logging

from openai import OpenAI

from anlagen_copilot.settings import get_settings

logger = logging.getLogger(__name__)


def embed(client: OpenAI, text: str) -> list[float]:
    """Embed one text and return the vector.

    Catches nothing on purpose. How far a failure reaches is something only the
    caller can know: here a text is a text, and whether losing it is bearable
    is decided by the loop above.

    Raises:
        BadRequestError: When the model rejects the input — practically always
            the token limit on a dense table page. Concerns exactly this text,
            which is why the caller decides what it means: `ingest_document()`
            skips the page, `check_embedding_config()` has no page to skip and
            lets the run end.
        OpenAIError: Every other case (authentication, rate limit, connection).
            Those would hit every further call just the same and should end the
            run — which is why nobody catches them further up either.
    """
    response = client.embeddings.create(
        model=get_settings().embedding_model,
        input=text,
        dimensions=get_settings().embedding_dimensions,
    )
    return response.data[0].embedding


def check_embedding_config(client: OpenAI) -> None:
    """Verify model, dimensions and API key with a single embedding call.

    Runs once before the ingestion loop, so a misconfiguration ends the run in a
    second instead of having to be inferred from a pattern of rejected pages.
    Deliberately goes through `embed()` rather than calling the API itself:
    whatever the ingestion sends later, the preflight has sent already, and the
    two cannot drift apart.

    Catches nothing. Every failure here concerns the whole run — a dimension the
    model will not take, an unknown model, a bad key — and none of them would
    look any different on the next document, so they are left to end it.
    """
    embed(client, "preflight")
    logger.info(
        "Embedding config verified: model '%s', %d dimensions",
        get_settings().embedding_model,
        get_settings().embedding_dimensions,
    )
