from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./governed_aiops.db"
    ingest_api_keys: str = "local-dev-ingest-key"
    operator_api_keys: str = ""
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    crewai_execution_enabled: bool = True
    serper_api_key: str | None = None
    rate_limit_requests: int = Field(default=120, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    prompt_version: str = "operational-report-v1"
    schema_version: str = "operational-report-schema-v1"

    @property
    def api_key_set(self) -> set[str]:
        return {key.strip() for key in self.ingest_api_keys.split(",") if key.strip()}

    @property
    def operator_key_set(self) -> set[str]:
        return {key.strip() for key in self.operator_api_keys.split(",") if key.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
