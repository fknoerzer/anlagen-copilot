"""Logging configuration for the application's entry points.

Deliberately its own module rather than a function in cli.py: `init_db.py` is a
second entry point that needs the same configuration without dragging in the
CLI dependencies (OpenAI client, corpus manifest).
"""

import logging

from anlagen_copilot.settings import get_settings

# httpx logs every request at INFO, openai adds headers and payload sizes at
# DEBUG. Across a 400-page manual that drowns out our own messages, so they are
# all raised by one level.
_NOISY_LIBRARIES = ("httpx", "httpcore", "openai")


def setup_logging() -> None:
    """Configures root logging for one entry point.

    Belongs in entry points only, never in library modules: the configuration
    takes effect process-wide, and a mere import should not force it on anyone.

    Repeated calls do no harm, but have no effect either: `basicConfig` returns
    immediately once the root logger already has a handler attached. A changed
    `log_level` therefore no longer takes hold.
    """
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
