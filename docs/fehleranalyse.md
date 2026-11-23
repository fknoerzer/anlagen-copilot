# Fehleranalyse

Grundlage: Lauf 19.10.2026 12:02 (`e85aab9`, `naive`) mit der Faktenprüfung vom 25.10.2026 15:55,
zum Vergleich einzelner Fälle die übrigen sieben v4-Läufe. 15 von 37 Fragen mit Befund.

| Frage | Typ | Beleg im Prompt | Zitiert | Fakten | Befund | Hebel |
|---|---|---|---|---|---|---|
| q-001 | diagram | 1/1 | 0/1 | — | Belegseite lag im Prompt, aber die Lage steht nur in der Explosionszeichnung; der Text enthält nur die Teileliste. Beide Läufe verweigern korrekt. | Vision-Modell |
| q-002 | diagram | 1/1 | 1/1 | unvollständig | Antwort nennt Feld [7] und „Th.Kl." korrekt. Die beiden räumlichen Fakten (mittig links außen, unter CosΦ) sind nur im Bild lesbar. | Vision-Modell |
| q-003 | diagram | 0/1 | — | — | Erwartete Seite 28 nicht gefunden. Lage des Motors ist Bildinhalt. | Vision-Modell |
| q-007 | multi-hop | 1/2 | 1/1 | unvollständig | Legende steht auf anderer Seite als die Tabelle, `naive` findet sie nie. Mit Legende im Prompt (`advanced`) trotzdem 3 von 3 falsch. | offen: Retrieval allein löst es nicht |
| q-008 | multi-hop | 0/2 | — | unvollständig | Motorenseite fehlt bei `naive`, Docling findet sie und beantwortet die Motorhälfte vollständig. Offen bleibt AUS2: statt S.501 wird immer S.513 gefunden. | Stichwortsuche (zu prüfen) |
| q-014 | diagram | 0/1 | — | unvollständig | Erwartet war die Drehmomentformel S.50, geliefert S.53–57, das Querkraft-Kapitel. Antwort korrekt und belegt, aber zur falschen Prüfung. | Stichwortsuche (zu prüfen) |
| q-015 | lookup | 0/1 | — | unvollständig | Antwort sagt richtig, dass die Formel nicht reicht, nennt dann Querkraft statt der thermischen Prüfung. Erwartete S.29 teilt kein Wort mit der Frage. | offen |
| q-018 | table | 1/1 | 1/1 | unvollständig | Antwort nennt Mobilgear 600 XP 220 statt Carter EP 220, pypdf verliert die Tabellenspalten; `naive` nennt in keinem der 5 Läufe alle vier richtig, einer verweigert, einer hält die Zuordnung für unmöglich. `advanced` nennt 3 von 3 die vier richtigen Produkte (Optigear BM 220, Klüberoil GEM 1-220 N, Shell Omala S2 GX Plus 220, Carter EP 220), der Fakt verlangt aber Herstellernamen, die im extrahierten Text nicht den Produkten zugeordnet sind. | Docling (`naive` 0 von 5, `advanced` 3 von 3); Fakt für v5 vorgemerkt |
| q-020 | lookup | 1/1 | 0/1 | unvollständig | Bei `naive` lag S.159 im Prompt und wurde nicht genutzt; die Antwort behauptet, die Angabe fehle. Das passiert in 2 von 5 `naive`-Läufen. `advanced` zitiert sie, vollständig. | Docling, wahrscheinlich; mit 3 Läufen nicht belegt (`naive` 3 von 5, `advanced` 3 von 3 richtig) |
| q-021 | table | 0/1 | — | unvollständig | Erwartete Schwellentabelle Katalog S.163 wird nie gefunden, stattdessen die thermischen Seiten der Betriebsanleitung. Rücksprache und Planschverluste richtig, Schwelle 2500 1/min fehlt. | offen |
| q-025 | table | 1/1 | 1/1 | unvollständig | Beleg lag vor und wurde zitiert. `naive` lässt das Derating weg, `advanced` nennt es in 2 von 3 Läufen für den gesamten Bereich statt oberhalb +40 °C. | offen: Generierung |
| q-028 | lookup | 0/1 | — | — | Erklärende Seite S.458 (Bedeutung der Präfixe A/F/N/C) wird nie gefunden, geliefert werden Seiten der Meldungsliste. Beide Läufe verweigern korrekt. | offen |
| q-033 | lookup | 0/1 | — | ok | Antwort in beiden Läufen vollständig und korrekt, zitiert aber S.18 statt der erwarteten S.19. Die Angabe steht auf beiden Seiten: S.18 in der Tabelle zum Oberflächenschutz, S.19 bei der Langzeitlagerung. | kein Systemfehler, Eval-Set |
| q-035 | multi-hop | 1/2 | 1/1 | unvollständig | Optionsseite S.28 mit allen vier Kürzeln fehlt im Hauptlauf und in allen drei `advanced`-Läufen; in den übrigen vier `naive`-Läufen liegt sie vor, und beide davon geprüften Antworten sind vollständig. `advanced` nennt /TF korrekt über S.115; der Ausschluss von /PK und /PT bleibt offen. | offen |
| q-036 | table | 0/1 | — | — | Erwartete S.369 wird nicht gefunden, obwohl sie bei q-025 gefunden wird. Geliefert werden SEW-Motorseiten. Beide Läufe verweigern korrekt. | offen |

## Kategorien

| Kategorie | Fragen | Was passiert |
|---|---:|---|
| Übersichts-, Legenden- oder Formelseite wird nicht gefunden | 5 (q-007, q-008, q-014, q-021, q-028) | Die Seite, die eine Tabelle oder ein Kürzel erst deutbar macht, enthält kaum Wörter aus der Frage. Seiten, die ausführlich über das Thema reden, ranken höher. |
| Inhalt steht nur im Bild | 3 (q-001, q-002, q-003) | Zeichnung oder Typenschild; der extrahierte Text enthält nur Positionsnummern. Das System verweigert korrekt. |
| Beleg lag vor, Generierung nutzt ihn falsch | 2 (q-020, q-025) | Bei q-020 ignoriert `naive` die Seite im Prompt, bei q-025 verallgemeinert `advanced` eine Bedingung. |
| Tabelle beim Extrahieren zerstört | 1 (q-018) | pypdf verliert die Spalten, die Antwort ordnet ein Produkt falsch zu. Mit Docling richtig, aber der Fakt ist auch dann nicht erfüllbar (siehe unten). |
| Eval-Set falsch, nicht das System | 1 (q-033) | Antwort vollständig, der Beleg zählt trotzdem als nicht gefunden. Solche Fälle machen die Zahlen zu schlecht, nicht zu gut. |
| Beleg nicht gefunden, Grund offen | 3 (q-015, q-035, q-036) | Kein erkennbares gemeinsames Muster. |

**Folge für die nächste Arbeit:** Die größte Kategorie ist nicht das Bildverständnis (3), sondern
die nicht gefundene erklärende Seite (5). Eine Stichwortsuche neben der Vektorsuche ist damit der
näherliegende Hebel als ein Vision-Modell. Beides ist nicht gemessen.

## Das Eval-Set ist falsch, nicht das System

| Frage | Mangel |
|---|---|
| q-003 | Frage fragt nach dem Einbau des Getriebes, erwarteter Fakt beschreibt die Lage des Motors |
| q-015 | Offene Frage mit mehreren richtigen Antworten, required_facts verlangen genau einen Zweig |
| q-018 | required_fact nennt Hersteller, der extrahierte Text der Quelltabelle nur Produkte (pypdf keinen Hersteller, Docling „FUCHS" und „TotalEnergies" ohne Spaltenbezug). Richtige Antwort wird verworfen |
| q-033 | expected_sources nennt nur S.19; die Angabe steht auch auf S.18, die Antwort ist korrekt |
| q-035 | Judge bewertet denselben Inhalt in zwei Läufen verschieden (einmal missing, einmal present) |

Diese Einträge bedeuten, dass die gemessenen Zahlen zu niedrig sind. Sie bleiben unverändert bis
Eval-Set v5, weil eine neue Version alle Zahlen im README unvergleichbar macht.
