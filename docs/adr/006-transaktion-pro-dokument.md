# ADR 006: Eine Transaktion pro Dokument

## Kontext

Ein Ingest-Lauf verarbeitet mehrere Handbücher. Ein Neu-Ingest muss den alten
Stand eines Dokuments vollständig ersetzen, auch wenn die Seitenmenge schrumpft
(etwa durch ein engeres `excerpt_pages`). Ein Abbruch mitten im Dokument darf
keinen halben oder leeren Stand hinterlassen.

## Entscheidung

- Jedes Dokument wird in einer eigenen Transaktion geschrieben: erst
  `DELETE` aller Chunks des Dokuments, dann die `INSERT`s.
- Der Download läuft außerhalb der Transaktion.
- Fehler, die genau ein Dokument betreffen (HTTP-Fehler, unlesbares PDF,
  falsche Seitenzahl, keine Seite mit Text), werden als `DocumentError`
  gemeldet. Das Dokument wird übersprungen, der Lauf geht weiter und endet mit
  Exit-Code 1.
- Lehnt das Embedding-Modell eine einzelne Seite ab, fehlt nur diese Seite.
  Das Dokument gilt dann als unvollständig, und der Lauf endet ebenfalls mit
  Exit-Code 1.
- Fehler, die jeden weiteren Aufruf genauso treffen (falscher API-Key,
  Verbindungsfehler), beenden den Lauf.

## Alternativen

- **Eine Transaktion über den ganzen Lauf.** Ein Fehler im letzten Dokument
  würde alle anderen verwerfen, und die Logzeilen entsprächen nicht dem
  Datenbankstand.
- **Upsert statt `DELETE` + `INSERT`.** Schrumpft die Seitenmenge, blieben
  Zeilen für nicht mehr gelesene Seiten stehen.

## Konsequenzen

- Nach einem Abbruch steht jedes Dokument entweder im alten oder im neuen
  Stand, nie leer.
- Ein Download blockiert keine offene Transaktion („idle in transaction").
- Ein unvollständiger Index geht nicht als erfolgreicher Lauf durch.
- Werden alle Seiten eines Dokuments abgelehnt, gilt das als `DocumentError`:
  Die Transaktion wird zurückgerollt, das Dokument behält seinen alten Stand,
  statt leer gespeichert zu werden, und der Lauf endet mit Exit-Code 1.
