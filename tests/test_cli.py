import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from helpers import UNAUTHORIZED, make_corpus, make_document, was_logged
from openai import AuthenticationError

from anlagen_copilot import cli
from anlagen_copilot.cli import main
from anlagen_copilot.corpus import CorpusDocument
from anlagen_copilot.errors import DocumentError


def _patch_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    documents: list[CorpusDocument],
    ingest: Mock,
) -> None:
    """Cuts `main()` loose from manifest, network and database.

    Patched in the `cli` namespace, which is the binding `main()` looks up;
    patching the defining module would leave it untouched.

    `get_connection()` is a `MagicMock` for the context manager alone: `with
    ... as conn` and `conn.transaction()` are magic methods a plain `Mock` does
    not answer. What runs on the connection is tested in `test_ingest.py`.
    """
    monkeypatch.setattr(cli, "setup_logging", Mock())
    monkeypatch.setattr(cli, "load_corpus", Mock(return_value=make_corpus(documents, tmp_path)))
    monkeypatch.setattr(cli, "get_openai_client", Mock())
    monkeypatch.setattr(cli, "check_embedding_config", Mock())
    monkeypatch.setattr(cli, "get_connection", MagicMock())
    monkeypatch.setattr(cli, "download_document", Mock())
    monkeypatch.setattr(cli, "ingest_document", ingest)


def test_main_finishes_without_exiting_when_every_page_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The green case: no `SystemExit`, no warning.

    Worth pinning next to the tests below, which a run that always exits 1
    would satisfy just as well.
    """
    documents = [make_document(id="doc-a"), make_document(id="doc-b")]
    _patch_main(monkeypatch, tmp_path, documents, Mock(return_value=0))

    with caplog.at_level(logging.INFO):
        main()

    assert was_logged(caplog, logging.INFO, "2 of 2 documents complete"), caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_main_books_the_rejected_pages_on_the_document_that_lost_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Three documents, and the counter belongs to the middle one.

    `doc-b` loses pages, `doc-c` fails after it: tallied outside the loop,
    `doc-b`'s three pages land on `doc-c`, the last value of the loop variable.
    One document in the fixture would not tell the two apart.
    """
    documents = [make_document(id=f"doc-{suffix}") for suffix in ("a", "b", "c")]
    ingest = Mock(side_effect=[0, 3, DocumentError("doc-c: unreadable")])
    _patch_main(monkeypatch, tmp_path, documents, ingest)

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 1
    assert was_logged(caplog, logging.WARNING, "1 documents incomplete: doc-b (-3 pages)"), (
        caplog.text
    )
    assert was_logged(caplog, logging.WARNING, "1 documents skipped: doc-c"), caplog.text
    # Both lists reach the log: an exit in the first branch would end the run
    # before the second was printed.
    assert was_logged(caplog, logging.INFO, "1 of 3 documents complete, 1 incomplete, 1 skipped"), (
        caplog.text
    )


def test_main_exits_1_for_a_document_that_is_merely_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing was skipped, and the run still is not green.

    The claim the return value was added for: the pages that made it stay, but
    a document with holes is not a complete ingestion.
    """
    _patch_main(monkeypatch, tmp_path, [make_document(id="doc-a")], Mock(return_value=2))

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 1
    assert was_logged(caplog, logging.WARNING, "1 documents incomplete: doc-a (-2 pages)"), (
        caplog.text
    )
    assert not was_logged(caplog, logging.WARNING, "documents skipped"), caplog.text


def test_main_lets_a_failure_of_the_whole_run_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad key ends the run instead of emptying the corpus document by document.

    `DocumentError` is the only failure the loop absorbs. The call count is the
    counter-check: an `except Exception` would carry on through the remaining
    two documents.
    """
    documents = [make_document(id=f"doc-{suffix}") for suffix in ("a", "b", "c")]
    ingest = Mock(side_effect=UNAUTHORIZED)
    _patch_main(monkeypatch, tmp_path, documents, ingest)

    with pytest.raises(AuthenticationError):
        main()

    assert ingest.call_count == 1
