from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Travel AI Concierge"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # UI (Milestone 3) — where the Streamlit app reaches the API. Distinct
    # from api_host (a bind address, e.g. 0.0.0.0) which isn't a valid
    # client-facing target in every environment.
    api_base_url: str = "http://localhost:8000"

    # Langfuse — works for both local self-hosted and Langfuse Cloud.
    # Switch between modes by changing these three values in .env only.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Default points at local self-hosted instance (started via `make langfuse-up`)
    langfuse_host: str = "http://localhost:3000"
    langfuse_enabled: bool = True
    # Flush traces synchronously in tests so nothing is silently dropped
    langfuse_flush_at_shutdown: bool = True

    # LLM provider
    llm_provider: str = "mock"
    llm_model: str = "mock"
    # Not passed to AnthropicProvider — the installed SDK's messages.create()
    # has no temperature parameter (verified by introspection, Milestone 2).
    # Kept for providers that do support it (e.g. a future OpenAIProvider).
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 30.0
    anthropic_api_key: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
