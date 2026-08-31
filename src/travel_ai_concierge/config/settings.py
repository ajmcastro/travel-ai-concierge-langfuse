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

    # Agent (Milestone 5) — flip to False to make /chat behave exactly like
    # Milestone 2 (direct provider call, no tools, no graph). This is the
    # one-line comparison the milestone spec asks for: "simple chatbot" vs.
    # "tool-using agent" traces, same endpoint, same provider config.
    agent_enabled: bool = True
    agent_max_iterations: int = 5
    # Milestone 6: versioned independently of app_version. app_version tracks
    # the whole deployable app's release; agent_version tracks only the
    # agent's own reasoning/graph logic, which can change without a full app
    # release (or vice versa). Maps to Langfuse's `version` propagation
    # attribute, whose own docstring names "agents" as the intended use case
    # for a second, independent version axis.
    agent_version: str = "1.0.0"

    # Milestone 7: how many prior turns (user+assistant exchanges) get
    # replayed into context on each /chat call. Bounds token growth per
    # conversation — the spec explicitly asks this project to be able to
    # observe "did context size grow excessively," and an unbounded history
    # is exactly that failure mode, not just a cost concern.
    max_history_turns: int = 10

    # Milestone 8: Langfuse Prompt Management. `prompt_label` is the whole
    # v1-vs-v2 comparison mechanism — flip to "staging" to run the other
    # seeded version with no code change. `prompt_cache_ttl_seconds` matches
    # the SDK's own default (60s); explicit here so it's a documented,
    # tunable knob rather than a value only visible by reading the SDK source.
    prompt_label: str = "production"
    prompt_cache_ttl_seconds: int = 60

    # Milestone 11: LLM-as-judge (Layer 2 evaluation). `judge_provider`
    # mirrors `llm_provider`'s pattern — "fake" (default, offline, free) or
    # "anthropic" (real, costs money/latency). `judge_model` is deliberately
    # a *separate* setting from `llm_model`, not reused — using a different
    # model/tier as judge than as the primary application model is the one
    # real (partial) mitigation available for the spec's "prefer an
    # independent judge model family" ask, since this project has no second
    # LLM vendor implemented — see evaluation/judge.py's module docstring.
    judge_provider: str = "fake"
    judge_model: str = "mock"

    # Milestone 17: regression detection. `make eval-ci` fails when either
    # metric drops by more than this from the committed baseline
    # (data/evaluation/baseline.json) — expressed as a max allowed drop in
    # the 0..1 rate, e.g. 0.05 = 5 percentage points. Two independent
    # thresholds, not one combined score, because Milestone 16 showed the
    # two metrics can move in opposite directions on the same regression.
    regression_max_quality_drop: float = 0.05
    regression_max_trajectory_drop: float = 0.05

    # Milestone 18: optional Travel AI Search integration. `travel_search_provider`
    # mirrors `llm_provider`'s pattern exactly — "local" (default, always
    # available, zero external services) or "travel_ai_search_api" (calls a
    # separately running Travel AI Search backend over HTTP). Demonstrates
    # service composition without a hard dependency: the app must still run
    # fully offline with "local", the same requirement the spec states for
    # the dataset itself ("The repository should work independently").
    travel_search_provider: str = "local"
    travel_ai_search_base_url: str = "http://localhost:8100"
    travel_ai_search_timeout_seconds: float = 10.0
    # Optional — sent as `Authorization: Bearer <key>` only when non-empty.
    # A real deployment of the separate Travel AI Search project may or may
    # not require auth; this project has no opinion on that, so it's unused
    # unless configured, same "empty string means not configured" convention
    # as `anthropic_api_key`.
    travel_ai_search_api_key: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
