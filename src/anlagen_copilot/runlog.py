"""Recording eval runs: which code a run measured, and one JSON line per run.

Shared by the retrieval and the generation evaluation. Both append to their
own file under `data/`, both mark a run by the commit it ran on, and both
format their timings the same way in the summary.
"""

import logging
import statistics
import subprocess
from pathlib import Path

from pydantic import BaseModel

from anlagen_copilot.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

# What a run's numbers depend on. The run files under `data/` stay out on
# purpose: every run appends to one, so the second of two back-to-back runs
# would be marked dirty although only the record of the first had changed.
_CODE_PATHS = ("src", "pyproject.toml", "uv.lock")


def current_commit(repo: Path = PROJECT_ROOT) -> str | None:
    """Return the short commit hash, marked `-dirty` over uncommitted code.

    A hash alone would claim a run for a commit that did not contain the code it
    ran. Only `_CODE_PATHS` count, and `status` rather than `diff`, so that a new
    module not yet added counts as well.

    `repo` rather than the working directory, because the paths are relative to
    it. None outside a repository: a missing hash makes a run harder to place
    later; failing the run over it would be worse.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *_CODE_PATHS],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    commit = head.stdout.strip()
    if not commit:
        return None
    return f"{commit}-dirty" if status.stdout.strip() else commit


def append_run(run: BaseModel, path: Path) -> None:
    """Append one run as a single JSON line.

    One record per line is the whole point of the format, so the JSON stays
    unindented: a pretty-printed record would break every reader that goes line
    by line, and it would break silently.

    A missing folder is created: each evaluation has its own folder under
    `data/`, and the first run of a new one should not fail over it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json() + "\n")
    logger.info("Run appended to %s", path)


def median_seconds(values: list[float]) -> str:
    """Format the median of the timings, or a dash when nothing was timed.

    The dash is needed because `statistics.median([])` raises instead of
    returning a value, and a run without reranking has no rerank timings.
    """
    return f"{statistics.median(values):.2f}s" if values else "—"
