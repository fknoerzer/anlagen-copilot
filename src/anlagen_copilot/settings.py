from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from anlagen_copilot.paths import PROJECT_ROOT


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and `.env`.

    Field names are the variable names, case-insensitively: `openai_api_key`
    comes from `OPENAI_API_KEY`. Fields without a default are mandatory and
    make instantiation fail when missing — which is why `get_settings()` defers
    it until something actually needs a value, rather than failing at import.

    Secrets are `SecretStr` so they stay masked in tracebacks and log output;
    reading the real value takes an explicit `.get_secret_value()`.
    """

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env")

    # Embeddings: OpenAI directly, for both ingestion strategies
    openai_api_key: SecretStr
    embedding_model: str = "text-embedding-3-large"

    # Generation: Anthropic
    anthropic_api_key: SecretStr
    generation_model: str = "claude-sonnet-5"

    # Azure: not before the Document Intelligence phase, hence optional
    azure_openai_endpoint: AnyHttpUrl | None = None
    azure_openai_api_key: SecretStr | None = None

    postgres_dsn: PostgresDsn
    llm_temperature: float = 0.0  # more deterministic for RAG

    ingest_strategy: Literal["naive", "advanced"] = "naive"

    embedding_dimensions: int = Field(default=1536, ge=1, le=2000)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Builds the settings on first actual use, not at import time."""
    return Settings()  # type: ignore[call-arg]  # required fields come from env/.env, not kwargs
