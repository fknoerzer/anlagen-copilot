"""The HTTP layer: the answer endpoint, its request, and the clients shared across requests."""

from functools import lru_cache
from typing import Annotated

from anthropic import Anthropic
from fastapi import APIRouter, Depends
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from anlagen_copilot.answer import AskResponse, answer
from anlagen_copilot.clients import get_anthropic_client, get_openai_client
from anlagen_copilot.db import get_connection
from anlagen_copilot.settings import Strategy, get_settings

router = APIRouter(prefix="/api")


class AskRequest(BaseModel):
    """One question to the manuals, as a user would ask it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=500)
    strategy: Strategy | None = Field(
        default=None, description="Which index to search; the configured one when unset."
    )


@lru_cache
def get_openai() -> OpenAI:
    """Build the OpenAI client on the first request and hand the same one to every later one.

    One client per process rather than per request: the client keeps its HTTP
    connections open, so later requests skip the TCP and TLS handshake. The
    endpoint gets it through `Depends`, so a test can swap in a fake with
    `app.dependency_overrides`.
    """
    return get_openai_client()


@lru_cache
def get_anthropic() -> Anthropic:
    """Build the Anthropic client on the first request and hand the same one to every later one."""
    return get_anthropic_client()


@router.post("/ask")
def ask(
    request: AskRequest,
    openai_client: Annotated[OpenAI, Depends(get_openai)],
    anthropic_client: Annotated[Anthropic, Depends(get_anthropic)],
) -> AskResponse:
    """Answer one question from the manuals, with the pages its statements cite.

    The search configuration comes from the `ask_*` settings, whose defaults
    are those of the measured generation runs, so the endpoint answers the way
    the evaluation was measured. Only the strategy may be chosen per request,
    so a client can put both indexes side by side.
    """
    settings = get_settings()

    with get_connection() as conn:
        return answer(
            openai_client,
            anthropic_client,
            request.question,
            conn,
            request.strategy or settings.ask_strategy,
            k=settings.ask_k,
            per_document=settings.ask_per_document,
            candidates=settings.ask_candidates,
            reranker=settings.ask_reranker,
            rerank_temperature=settings.rerank_temperature,
            generation_model=settings.generation_model,
        )
