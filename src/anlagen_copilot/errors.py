class DocumentError(Exception):
    """An error confined to exactly one document — the run can carry on.

    The line against everything else: what does not come through here concerns
    the whole run (missing API key, database gone) and should end it.
    """
