from functools import lru_cache

from pydantic import AnyHttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    azure_openai_endpoint: AnyHttpUrl
    azure_openai_api_key: SecretStr
    azure_openai_deployment: str = "gpt-5-mini"
    embedding_deployment: str = "text-embedding-3-large"
    postgres_dsn: PostgresDsn
    llm_temperature: float = 0.0  # deterministischer für RAG


@lru_cache
def get_settings() -> Settings:
    """Baut die Settings erst bei tatsächlicher Nutzung, nicht beim Import."""
    return Settings()  # type: ignore[call-arg]  # Pflichtfelder kommen aus Env-Vars/.env, nicht aus Kwargs
