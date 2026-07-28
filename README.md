# Anlagen-Copilot

## Voraussetzungen

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL mit [pgvector](https://github.com/pgvector/pgvector)

## Setup

```bash
uv sync --all-extras --dev
cp .env.example .env  # Werte eintragen (Azure OpenAI, Postgres-DSN)
uv run pre-commit install
```

## Verwendung

```bash
uv run anlagen-copilot
```

## Entwicklung

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run pytest --cov=src
```
