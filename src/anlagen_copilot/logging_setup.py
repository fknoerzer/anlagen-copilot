"""Logging-Konfiguration für die Einstiegspunkte der Anwendung.

Bewusst ein eigenes Modul statt einer Funktion in cli.py: `init_db.py` ist ein
zweiter Einstiegspunkt, der dieselbe Konfiguration braucht, aber nicht die
CLI-Abhängigkeiten (OpenAI-Client, Korpus-Manifest) mitziehen soll.
"""

import logging

from anlagen_copilot.settings import get_settings

# httpx protokolliert jede Anfrage auf INFO, openai zusätzlich Header und
# Payload-Größen auf DEBUG. Über ein 400-Seiten-Handbuch hinweg ersäuft das die
# eigenen Meldungen, deshalb pauschal eine Stufe höher gehängt.
_NOISY_LIBRARIES = ("httpx", "httpcore", "openai")


def setup_logging() -> None:
    """Konfiguriert das Root-Logging für einen Einstiegspunkt.

    Gehört ausschließlich in Einstiegspunkte, nie in Bibliotheksmodule: die
    Konfiguration wirkt prozessweit, und ein bloßer Import soll sie niemandem
    aufzwingen.

    Mehrfachaufrufe sind unschädlich, aber auch wirkungslos: `basicConfig`
    kehrt sofort zurück, sobald am Root-Logger bereits ein Handler hängt.
    Eine geänderte `log_level` greift dann also nicht mehr.
    """
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
