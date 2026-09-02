"""VMSG API settings — pydantic-settings, env-driven, .env-friendly."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "vmsg-api"
    version: str = "0.1.0"
    debug: bool = False

    database_url: str = "postgresql://vmsg:vmsg@localhost:5432/vmsg"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "vmsg-dev-password"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-only-change-me"
    access_token_ttl_seconds: int = 900          # 15-min access tokens (SEC-01)
    refresh_token_ttl_days: int = 30
    offline_token_secret: str = "dev-only-change-me-too"

    api_v1_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
