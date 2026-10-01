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

Jeder Lauf beantwortet alle 36 Fragen, zählt korrekte und falsche Ablehnungen und wie viele der Belegseiten, die im Prompt lagen, die Antwort zitiert. Er hängt eine Zeile an `data/generation/eval_runs.jsonl` an, mit der vollständigen Antwort je Frage.

## Entwicklungsbefehle

```bash
uv run pre-commit install
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run pytest --cov=src
```
