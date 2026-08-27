class DocumentError(Exception):
    """Fehler, der genau ein Dokument betrifft — der Lauf kann weiterlaufen.

    Abgrenzung zu allem anderen: Was hier nicht durchkommt, betrifft den
    gesamten Lauf (fehlender API-Key, Datenbank weg) und soll ihn abbrechen.
    """
