# ADR 007: Embedding-Konfiguration vor dem ersten Download prüfen

## Kontext

Ein falscher API-Key, ein unbekanntes Modell oder eine Dimension, die das
Modell nicht liefert, zeigten sich ursprünglich erst beim ersten Embedding,
nach dem Download des ersten Handbuchs.

## Entscheidung

`check_embedding_config()` schickt vor dem ersten Download und vor dem Öffnen
der Datenbankverbindung einen einzelnen Embedding-Aufruf. Er läuft über
dieselbe Funktion `embed()` wie die Ingestion und fängt keine Fehler ab.

## Alternativen

- **Eigener Prüfaufruf an der API vorbei.** Probe und Ingestion könnten
  auseinanderlaufen, etwa bei einem Parameter, den nur einer von beiden setzt.

## Konsequenzen

- Eine falsche Konfiguration beendet den Lauf nach einer Sekunde.
- Nicht abgedeckt: ob die Dimension zum bestehenden Tabellenschema passt. Das
  fällt erst beim ersten `INSERT` auf.
