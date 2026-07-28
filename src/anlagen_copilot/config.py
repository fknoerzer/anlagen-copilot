from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str = "gpt-5-mini"
    embedding_deployment: str = "text-embedding-3-large"
    postgres_dsn: str
    llm_temperature: float = 0.0  # deterministischer für RAG


settings = Settings()  # type: ignore[call-arg]
