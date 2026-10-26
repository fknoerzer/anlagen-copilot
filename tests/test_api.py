from collections.abc import Iterator
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from helpers import NO_ANTHROPIC, NO_CLIENT, make_answer

from anlagen_copilot import api, pipeline
from anlagen_copilot.answer import AskResponse, answer
from anlagen_copilot.app import app
from anlagen_copilot.corpus import load_corpus
from anlagen_copilot.generate import Generated
from anlagen_copilot.pipeline import PageSelection
from anlagen_copilot.retrieval import Source
from anlagen_copilot.settings import Strategy

_PAGES = [
    Source(document_id="sew-getriebe-ba", page=22, score=0.71, content="Typenschild " * 60),
    Source(document_id="siemens-g120c-kurz", page=270, score=0.64, content="STO und Not-Halt"),
]


def _patch_pipeline(monkeypatch: pytest.MonkeyPatch, *statements: tuple[str, list[int]]) -> Mock:
    """Replaces both stages where `answer_question()` looks them up; returns the search mock."""
    select = Mock(
        return_value=PageSelection(
            candidates=_PAGES,
            pages=_PAGES,
            retrieval_seconds=0.2,
            rerank_seconds=2.0,
            rerank_input_tokens=100,
            rerank_output_tokens=10,
        )
    )
    generated = Generated(
        answer=make_answer(True, *statements), model="m", input_tokens=500, output_tokens=40
    )
    monkeypatch.setattr(pipeline, "select_pages", select)
    monkeypatch.setattr(pipeline, "generate", Mock(return_value=generated))
    return select


def _answer(strategy: Strategy = "advanced") -> AskResponse:
    return answer(
        NO_CLIENT,
        NO_ANTHROPIC,
        "Kann ich STO als Not-Aus verwenden?",
        MagicMock(),
        strategy,
        k=5,
        per_document=None,
        candidates=20,
        reranker="test-reranker",
        rerank_temperature=0.0,
        generation_model="test-generator",
    )


def test_answer_points_each_statement_at_the_page_it_cites(monkeypatch: pytest.MonkeyPatch) -> None:
    """Statement [2] is the second page in the prompt; a client looks it up as citations[1]."""
    _patch_pipeline(monkeypatch, ("STO eignet sich für Not-Halt.", [2]))

    result = _answer()

    [statement] = result.statements
    cited = result.citations[statement.sources[0] - 1]
    assert (cited.n, cited.document_id, cited.page) == (2, "siemens-g120c-kurz", 270)


def test_answer_links_each_citation_to_its_page_in_the_manufacturers_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pipeline(monkeypatch, ("Aussage", [1]))
    documents = {d.id: d for d in load_corpus().documents}

    result = _answer()

    assert [c.url for c in result.citations] == [
        f"{documents['sew-getriebe-ba'].url}#page=22",
        f"{documents['siemens-g120c-kurz'].url}#page=270",
    ]
    assert result.citations[1].title == documents["siemens-g120c-kurz"].title


def test_answer_keeps_the_pages_it_did_not_cite_and_cuts_their_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both pages become cards, the uncited one too; the long page is cut to an excerpt."""
    _patch_pipeline(monkeypatch, ("Aussage", [2]))

    result = _answer()

    assert [c.n for c in result.citations] == [1, 2]
    assert len(result.citations[0].excerpt) == 300


def test_answer_runs_the_search_with_the_configuration_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint must search the way the eval measured; nothing on the way may drop a setting."""
    select = _patch_pipeline(monkeypatch, ("Aussage", [1]))

    _answer(strategy="naive")

    assert select.call_args.args[4] == "naive"
    assert {k: select.call_args.kwargs[k] for k in ("k", "candidates", "reranker")} == {
        "k": 5,
        "candidates": 20,
        "reranker": "test-reranker",
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Mock]]:
    """A client for the app with clients, database and `answer()` replaced; yields the mock."""
    answered = Mock(return_value=AskResponse(answered=False, statements=[], citations=[]))
    monkeypatch.setattr(api, "answer", answered)
    monkeypatch.setattr(api, "get_connection", MagicMock())
    app.dependency_overrides[api.get_openai] = lambda: NO_CLIENT
    app.dependency_overrides[api.get_anthropic] = lambda: NO_ANTHROPIC
    yield TestClient(app), answered
    app.dependency_overrides.clear()


def test_ask_searches_the_configured_index_when_the_request_names_none(
    client: tuple[TestClient, Mock],
) -> None:
    """`ask_strategy`, not `ingest_strategy`: re-ingesting must not change what is searched."""
    test_client, answered = client

    response = test_client.post("/api/ask", json={"question": "Wie oft warten?"})

    assert response.status_code == 200
    assert answered.call_args.args[4] == "advanced"


def test_ask_searches_the_index_the_request_names(client: tuple[TestClient, Mock]) -> None:
    test_client, answered = client

    test_client.post("/api/ask", json={"question": "Wie oft warten?", "strategy": "naive"})

    assert answered.call_args.args[4] == "naive"


@pytest.mark.parametrize(
    "body",
    [{"question": ""}, {"question": "x" * 501}, {"question": "Frage", "strategy": "agentic"}],
)
def test_ask_rejects_a_request_outside_its_contract(
    client: tuple[TestClient, Mock], body: dict[str, str]
) -> None:
    """Refused before any search runs, so a malformed request costs no tokens."""
    test_client, answered = client

    response = test_client.post("/api/ask", json=body)

    assert response.status_code == 422
    answered.assert_not_called()
