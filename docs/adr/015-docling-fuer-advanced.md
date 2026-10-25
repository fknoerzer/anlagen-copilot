# ADR 015: Docling als Extraktion der Strategie `advanced`

## Kontext

pypdf liest eine Seite als flachen Text. Tabellen verlieren dabei ihre Spalten:
Auf `siemens-g120c-kurz` S. 270 (q-010) steht nach der Extraktion nicht mehr
fest, welcher Satz zu Not-Aus und welcher zu Not-Halt gehört
([ADR 001](001-seite-als-chunk.md)). Die Strategie `advanced`
([ADR 002](002-strategie-als-spalte.md)) soll das mit einer layoutbewussten
Extraktion beheben und gegen `naive` gemessen werden.

Proben mit Docling 2.141 an einzelnen Seiten:

- S. 270 kommt als Markdown-Tabelle, jede Zelle in ihrer Spalte.
- Der Text in Vektorzeichnungen (Typenschild, `sew-getriebe-ba` S. 22, q-002)
  steht im Dokument, fehlt aber im Markdown-Export, solange
  `traverse_pictures` nicht gesetzt ist. Ein Fehler entsteht dabei nicht.
- Die verschlüsselten SEW-Handbücher öffnen ohne Passwort, `doc.pages` zählt
  die Seiten des Original-PDFs.
- OCR auf Bildbereichen liest die EFF-Klassenzeichen im Projektierungskatalog
  (S. 16, q-034), die in der Textebene fehlen. Sie kostet Zeit: 6–8 s je Seite
  mit, 1,4–2,8 s ohne, gemessen an zwei Seiten.

Im ersten Ingest lieferte Docling für den Projektierungskatalog auf 209 von 248
Seiten 4.354 Ersatzzeichen (U+FFFD) statt Umlauten und ß. pypdf liest dieselben
Seiten richtig. Ursache ist die Hauptschrift des Katalogs von 2006: Sie liefert
cp1252-Bytes, deren Kodierung jeder Leser erraten muss. Das Standard-Backend
von Docling gibt diese Zeichen auf, pypdfium2 liest sie als MacRoman („m¸ssen“),
und PDFium zerlegt dabei die Ligatur „ﬂ“, die für „ß“ steht, in die Buchstaben
„f“ und „l“.

## Entscheidung

`advanced` liest mit Docling statt pypdf und bleibt bei einer Seite je Chunk,
damit die Wirkung der Extraktion allein messbar ist. Im Einzelnen
(`extract_pages_docling()`, `_converter()`):

- OCR bleibt an, für Bildbereiche.
- Der Markdown-Export läuft mit `traverse_pictures=True`, ohne Bild-Platzhalter,
  ohne HTML-Maskierung und mit kompakten Tabellen.
- Der Seitenbereich geht als `page_range` an Docling, nicht als Schnitt danach.
- Ein `PARTIAL_SUCCESS` lässt das Dokument scheitern wie ein Fehler
  ([ADR 005](005-kein-stiller-rueckfall.md)).
- Die Extraktion läuft vor der Transaktion des Dokuments, weil sie Minuten
  dauert ([ADR 006](006-transaktion-pro-dokument.md)).

Für Dokumente mit defekter Textebene steht der Befund im Manifest,
`text_encoding_defect: cp1252_as_macroman`, heute nur beim Katalog. Für sie liest
Docling über pypdfium2, eine Tabelle ordnet die falsch gelesenen Zeichen zurück
(„¸“ → „ü“), und das ß setzt ein Abgleich mit dem pypdf-Text derselben Seite
wieder ein: Ein Wort wird nur ersetzt, wenn pypdf es mit „ß“ kennt und nicht mit
„fl“. Bleibt danach ein U+FFFD, scheitert das Dokument. Ohne angegebenen Defekt
wird ein U+FFFD nur gezählt und geloggt.

Ergebnis auf dem Katalog (`e2a86c3`): 0 Ersatzzeichen, 3.553 Umlaute, 417 von
445 ß, im Median 93,6 % gemeinsame Wörter mit pypdf je Seite.

## Alternativen

- **Azure Document Intelligence.** Kostet je Seite und schickt die Handbücher an
  einen Cloud-Dienst; Docling läuft lokal und kostenlos. Für später nicht
  ausgeschlossen.
- **Die Chunker von Docling (`HybridChunker`).** Gäben das Schneiden aus der
  Hand ([ADR 010](010-kein-rag-framework.md)) und änderten zwei Dinge auf
  einmal.
- **OCR aus.** Zwei- bis fünfmal schneller, verliert aber Text, den eine Seite
  nur als Bild zeigt.
- **Volle OCR für den Katalog** (`OcrMode.FULL_PAGE`, deutsches Modell). Auf 11
  Katalogseiten 67,9–98,1 % gemeinsame Wörter gegen 83,9–100 % mit der
  Reparatur, 5–14 s je Seite. Tabellenzellen nimmt Docling auch dabei aus der
  Textebene, auch mit `do_cell_matching=False`: Auf S. 19, 30 und 230 blieben
  59, 30 und 40 Ersatzzeichen.
- **Wörter mit U+FFFD gegen pypdf auflösen**, ohne zweites Backend. Löste auf 11
  Seiten 242 von 276 kaputten Wörtern eindeutig, hochgerechnet blieben im
  Katalog rund 500 Wörter wie „über“ oder „gemäß“ kaputt.
- **Den Katalog unter `advanced` mit pypdf lesen.** Einfach, aber 8 der 32
  beantwortbaren Fragen hängen am Katalog, darunter die Tabellenfrage q-021,
  und für sie würde `advanced` nichts Neues messen.
- **Rückfall je Seite auf pypdf, wo Ersatzzeichen auftreten.** Träfe 209 der
  248 Katalogseiten und damit gerade die Tabellen.

## Konsequenzen

- Erster Messpunkt, Retrieval ohne Reranker auf Eval-Set v4: `naive` 24 / 36 in
  den Top 5 und 33 / 36 in den Top 50 (`e85aab9`), `advanced` 22 / 36 und
  33 / 36, vor (`dbbe947`) wie nach der Reparatur (`e2a86c3`). Die Reparatur
  bewegt die Ränge der Katalogfragen kaum (q-020 von 11 auf 8); die Verluste
  kommen aus der Umstrukturierung selbst: q-020 fällt von Rang 1 auf 8, q-016
  aus den Top 5, die SEW-Seite zu q-035 aus den Top 50.
- q-021 findet keine Strategie, obwohl Docling die Tabelle auf S. 163 sauber
  extrahiert. Der Engpass dort ist die Suche, nicht die Extraktion; ein Kandidat
  für Chunks kleiner als eine Seite.
- Ein Ingest mit `advanced` dauert auf der CPU rund 1 h 40 min für 1.334 Seiten.
  `import anlagen_copilot.ingest` dauert 7,7 s, auch für `naive`.
- Docling verwirft vereinzelt Tabellenzellen, die es keiner Zeile oder Spalte
  zuordnen kann (Warnung `MatchingPostProcessor`, meist 1–5, einmal 10 von 162
  Zellen).
- Die Reparatur ist auf einen Defekt zugeschnitten. Ein neues Dokument mit
  anderem Schriftfehler braucht einen eigenen Befund im Manifest; bis dahin
  zeigt die Warnung zu U+FFFD, wo (heute: eine Seite in `sew-motoren-drn`, 9
  Zeichen). Rund 20 ß bleiben „fl“, wo pypdf das Wort am Zeilenende trennt.
