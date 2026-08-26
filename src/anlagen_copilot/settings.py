from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # Embeddings: OpenAI direkt, für beide Ingestion-Strategien
    openai_api_key: SecretStr
    embedding_model: str = "text-embedding-3-large"

    # Generation: Anthropic
    anthropic_api_key: SecretStr
    generation_model: str = "claude-sonnet-5"

    # Azure: erst ab der Document-Intelligence-Phase, deshalb optional
    azure_openai_endpoint: AnyHttpUrl | None = None
    azure_openai_api_key: SecretStr | None = None

    postgres_dsn: PostgresDsn
    llm_temperature: float = 0.0  # deterministischer für RAG

    ingest_strategy: Literal["naive", "advanced"] = "naive"

    embedding_dimensions: int = 1536


@lru_cache
def get_settings() -> Settings:
    """Baut die Settings erst bei tatsächlicher Nutzung, nicht beim Import."""
    return Settings()  # type: ignore[call-arg]  # Pflichtfelder kommen aus Env-Vars/.env, nicht aus Kwargs
