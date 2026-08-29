from functools import lru_cache

from langfuse import Langfuse

from travel_ai_concierge.config import get_settings


@lru_cache(maxsize=1)
def get_langfuse_client() -> Langfuse:
    """Return the process-wide Langfuse client, configured from Settings.

    We build this explicitly from our own Settings rather than relying on the
    SDK's env-var auto-discovery (`get_client()`), because pydantic-settings
    reads `.env` into the Settings object without mutating `os.environ` — the
    SDK would see nothing. Constructing the client is local-only (no network
    call happens here; spans are batched and exported asynchronously on
    flush/shutdown), so this is safe to call from a FastAPI startup hook.

    When `langfuse_enabled` is False, we still return a real client with
    `tracing_enabled=False` rather than `None` — call sites never need an
    `if enabled:` branch, and observability never becomes a hard runtime
    dependency (see ADR-004).
    """
    settings = get_settings()
    return Langfuse(
        public_key=settings.langfuse_public_key or None,
        secret_key=settings.langfuse_secret_key or None,
        host=settings.langfuse_host,
        environment=settings.environment,
        release=settings.app_version,
        tracing_enabled=settings.langfuse_enabled,
    )
