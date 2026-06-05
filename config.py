from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BE_",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "DEBUG"

    # Supabase
    supabase_url: str
    supabase_service_role_key: str

    # MongoDB
    mongo_uri: str
    mongo_db_name: str = "pattern_proof"

    # Neo4j
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # Redis
    redis_url: str

    # Messaging
    event_bus: str = "eager"  # eager | redpanda
    redpanda_bootstrap_servers: str = "localhost:9092"

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 30

    # LLM
    anthropic_api_key: str
    ollama_base_url: str
    ollama_api_key: str | None = None
    gemma_model: str = "gemma2:27b"
    claude_model: str = "claude-sonnet-4-6"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
