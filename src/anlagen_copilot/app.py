"""The FastAPI app that serves the answer endpoint under `/api`, and its start command."""

import uvicorn
from fastapi import FastAPI

from anlagen_copilot.api import router
from anlagen_copilot.logging_setup import setup_logging

app = FastAPI()
app.include_router(router)


def main() -> None:
    """Serve the app on this machine. Entry point for `anlagen-copilot-api`.

    Bound to 127.0.0.1, not to every interface: each request spends API tokens,
    and the endpoint has no authentication, so it stays reachable from this
    machine only. For development with reload on save, run
    `uv run uvicorn anlagen_copilot.app:app --reload` instead.
    """
    setup_logging()
    uvicorn.run(app, host="127.0.0.1", port=8000)
