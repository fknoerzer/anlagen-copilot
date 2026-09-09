"""The project's one exception type, raised across ingestion and download.

`cli.main()` is the only place that catches it.
"""


class DocumentError(Exception):
    """An error confined to exactly one document — the run can carry on.

    The line against everything else: what does not come through here concerns
    the whole run (missing API key, database gone) and should end it.
    """
