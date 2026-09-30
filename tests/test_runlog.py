import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from anlagen_copilot.runlog import append_run, current_commit


class _Run(BaseModel):
    """A stand-in run: `append_run()` takes any model, not one eval's run type."""

    commit: str
    note: str = ""


def _raise(exc: Exception) -> object:
    """Builds a `subprocess.run` stand-in that fails with `exc`."""

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise exc

    return run


def _git(repo: Path, *args: str) -> str:
    """Runs git in `repo` and returns its trimmed output."""
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    """Builds a repository with one commit over the paths `current_commit()` tells apart.

    `src/app.py` stands for code, `data/retrieval/eval_runs.jsonl` for the record
    every run appends to. Identity and signing are set per command, so the test
    does not depend on how git is configured on the machine running it.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text('print("code")\n', encoding="utf-8")
    runs = tmp_path / "data" / "retrieval" / "eval_runs.jsonl"
    runs.parent.mkdir(parents=True)
    runs.write_text('{"run": 1}\n', encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "init",
    )
    return tmp_path


def test_current_commit_marks_uncommitted_code_dirty(tmp_path: Path) -> None:
    """A run on code that is not committed must not pass for the commit below it."""
    repo = _make_repo(tmp_path)
    (repo / "src" / "app.py").write_text('print("changed")\n', encoding="utf-8")

    assert current_commit(repo) == _git(repo, "rev-parse", "--short", "HEAD") + "-dirty"


def test_current_commit_ignores_an_appended_eval_run(tmp_path: Path) -> None:
    """The record of one run does not mark the next run dirty.

    Running k=5 and k=20 back to back is the usual case; flagging the second would
    make the marker a false alarm exactly where it should be trusted.
    """
    repo = _make_repo(tmp_path)
    with (repo / "data" / "retrieval" / "eval_runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"run": 2}\n')

    assert current_commit(repo) == _git(repo, "rev-parse", "--short", "HEAD")


def test_current_commit_is_none_outside_a_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _raise(subprocess.CalledProcessError(128, "git")))

    assert current_commit() is None


def test_current_commit_is_none_when_git_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _raise(FileNotFoundError("git")))

    assert current_commit() is None


def test_append_run_keeps_the_earlier_run(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    first_run = _Run(commit="aaa1111")
    second_run = _Run(commit="bbb2222")

    append_run(first_run, path)
    append_run(second_run, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [_Run.model_validate_json(line) for line in lines] == [first_run, second_run]


def test_append_run_round_trips_non_ascii(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    run = _Run(commit="abc1234", note="mödél")

    append_run(run, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [_Run.model_validate_json(line) for line in lines] == [run]


def test_append_run_creates_a_missing_folder(tmp_path: Path) -> None:
    """The first run of a new evaluation writes into a folder that does not exist yet."""
    path = tmp_path / "generation" / "eval_runs.jsonl"

    append_run(_Run(commit="abc1234"), path)

    assert path.is_file()
