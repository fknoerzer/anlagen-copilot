# Setup

Die ausführliche Fassung des [Schnellstarts](../README.md#schnellstart) im README.

## Voraussetzungen

- Python 3.12 und [uv](https://docs.astral.sh/uv/)
- Docker (für PostgreSQL mit pgvector)
- API-Keys für OpenAI (Embeddings) und Anthropic (Reranking und Generierung)

## 1. Repository klonen

```bash
git clone https://github.com/fknoerzer/anlagen-copilot.git
cd anlagen-copilot
```

## 2. Abhängigkeiten installieren und konfigurieren

```bash
uv sync --dev
cp .env.example .env   # OPENAI_API_KEY und ANTHROPIC_API_KEY eintragen
```

## 3. Datenbank starten und Schema anlegen

```bash
docker compose up -d
uv run python -m anlagen_copilot.scripts.init_db
```

## 4. Korpus laden und indexieren

```bash
uv run anlagen-copilot
```

Die PDFs liegen aus urheberrechtlichen Gründen nicht im Repository. Sie werden beim ersten Lauf anhand der URLs in `data/raw/corpus.yaml` von den Herstellerseiten geladen. Das Manifest hält zu jedem Dokument Titel, Hersteller, Ausgabe, Bezugsdatum und Quelle fest, damit nachvollziehbar bleibt, auf welcher Dokumentversion die Messwerte beruhen.

Die 6 Handbücher haben zusammen 1.810 Seiten. Davon werden 1.334 Seiten eingelesen, 1.322 mit extrahierbarem Text landen im Index: Aus dem 572-seitigen Siemens-Listenhandbuch wird nur Kapitel 4 „Störungen und Warnungen" (S. 453–548) eingelesen, weil die Fragen der Instandhaltung dort ansetzen. Die übrigen Kapitel (rund 310 Seiten Parameterlisten, 135 Seiten Funktionspläne und der Anhang) sind bewusst ausgelassen.

Die Strategie `advanced` liest dieselben Seiten mit Docling statt pypdf und schreibt sie neben die `naive`-Chunks in dieselbe Tabelle ([ADR 002](adr/002-strategie-als-spalte.md)):

```bash
INGEST_STRATEGY=advanced uv run anlagen-copilot
```

Unter PowerShell setzt man die Variable vorher mit `$env:INGEST_STRATEGY = "advanced"`, oder dauerhaft in der `.env`. Docling lädt beim ersten Lauf seine Modelle herunter (rund 570 MB) und rechnet auf der CPU 1,5 bis 8 Sekunden je Seite, mit OCR eher am oberen Ende; für alle 1.334 Seiten ist mit ein bis zwei Stunden zu rechnen.

## 5. Retrieval evaluieren

```bash
# Nur Vektorsuche
uv run python -m anlagen_copilot.scripts.eval_retrieval --k 5

# Mit Reranking: 20 Kandidaten holen, auf 5 eindampfen
uv run python -m anlagen_copilot.scripts.eval_retrieval --k 5 --candidates 20 --reranker claude-haiku-4-5-20251001
```

Jeder Lauf hängt eine Zeile an `data/retrieval/eval_runs.jsonl` an. Die datierte Modell-ID statt des Alias `claude-haiku-4-5` hält die Läufe vergleichbar: Ein Alias kann später auf ein neueres Modell zeigen.

## 6. Antworten evaluieren

```bash
# Reranking wie oben, Generierung mit dem konfigurierten Modell
uv run python -m anlagen_copilot.scripts.eval_generate --k 5 --candidates 20 --reranker claude-haiku-4-5-20251001

# Anderes Generierungsmodell zum Vergleich
uv run python -m anlagen_copilot.scripts.eval_generate --k 5 --candidates 20 --reranker claude-haiku-4-5-20251001 --generator claude-haiku-4-5-20251001
```

Jeder Lauf beantwortet alle 37 Fragen, zählt korrekte und falsche Ablehnungen und wie viele der Belegseiten, die im Prompt lagen, die Antwort zitiert. Er hängt eine Zeile an `data/generation/eval_runs.jsonl` an, mit der vollständigen Antwort je Frage.

## API starten

```bash
uv run anlagen-copilot-api
```

Startet die API auf `http://127.0.0.1:8000`, nur von diesem Rechner aus erreichbar; zum Ausprobieren `http://127.0.0.1:8000/docs`. Die Datenbank muss laufen (`docker compose up -d`). Zum Entwickeln mit Neuladen beim Speichern: `uv run uvicorn anlagen_copilot.app:app --reload`.

Eine kleine Oberfläche, die die API aufruft, liegt in `ui/app.py`. Sie braucht das optionale Extra `ui` und läuft neben der API:

```bash
uv run --extra ui streamlit run ui/app.py
```

Im Modus „Vergleich“ geht jede Frage an beide Indizes, das kostet doppelt (rund 6 statt 3 Cent). Nach einer Änderung in `src/` müssen API und Oberfläche neu starten; ein Rerun in Streamlit lädt nur `ui/app.py` neu.

## Entwicklungsbefehle

```bash
uv run pre-commit install
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run pytest --cov=src
uv run pytest -m docling   # Docling-Tests, laden beim ersten Mal die Modelle herunter
```
