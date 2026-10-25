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

- Gemessen auf Eval-Set v4, je drei Läufe mit Reranker und Generierung
  (`naive` `e85aab9`, `advanced` `c4e7435`): Reranking 27 statt 25–26 von 36
  Belegen in den Top 5, Multi-Hop 6 statt 4–5 von 8; Antworten mit allen
  Fakten 61–62 % statt 64–74 %. Ohne Reranker 22 statt 24 von 36
  (`e2a86c3`). Docling hilft also dem Reranking, noch nicht den Antworten.
- Strukturiert ist nicht immer besser: SEW-Motoren S. 28 (q-035) besteht unter
  Docling aus kleinen Tabellen mit gleichen Kopfzeilen und fällt aus den Top 50
  der Vektorsuche.
- q-021 findet keine Strategie, obwohl Docling die Tabelle auf S. 163 sauber
  extrahiert; der Engpass ist dort die Suche.
- Reranking und Generierung lesen 16 % bzw. 10 % mehr Input-Tokens. Ein Ingest
  dauert auf der CPU rund 1 h 40 min, `import anlagen_copilot.ingest` 7,7 s,
  auch für `naive`.
- Docling verwirft vereinzelt Tabellenzellen, die es keiner Zeile oder Spalte
  zuordnet (Warnung `MatchingPostProcessor`, meist 1–5 Zellen).
- Die Reparatur gilt nur für den einen Defekt; ein anderer Schriftfehler braucht
  einen eigenen Befund. Rund 20 ß bleiben „fl“, wo pypdf das Wort trennt.
