from langfuse.model import TextPromptClient

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client

SYSTEM_PROMPT_NAME = "travel-concierge-system"

# The local fallback if Langfuse is unreachable or the prompt hasn't been
# seeded yet (`make seed-prompts`) — also the exact text seeded as prompt
# version 1 (`Settings.prompt_label` default "production"), so the app
# behaves identically whether or not Langfuse happens to be reachable.
SYSTEM_PROMPT_FALLBACK = (
    "You are a helpful, concise travel concierge. Ask clarifying questions when "
    "important details (destination, dates, budget, travellers) are missing. Use "
    "the available tools to look up real destination and hotel information rather "
    "than guessing."
)


def get_system_prompt() -> TextPromptClient:
    """Fetch the system prompt from Langfuse Prompt Management, by label.

    Never raises: `fallback=SYSTEM_PROMPT_FALLBACK` means an unreachable
    Langfuse host, a prompt that hasn't been seeded yet, or any other fetch
    error all resolve to a synthetic PromptClient carrying the fallback text
    (`.is_fallback` is True) instead of an exception propagating — the
    literal requirement from the Milestone 8 spec: "Do not make the
    application unable to start if remote prompt retrieval fails."

    `Settings.prompt_label` (default "production") is the whole comparison
    mechanism: flip it to "staging" to run against prompt v2 with no code
    change, the same pattern `agent_enabled`/`llm_provider` already use.
    """
    settings = get_settings()
    client = get_langfuse_client()
    return client.get_prompt(
        SYSTEM_PROMPT_NAME,
        label=settings.prompt_label,
        type="text",
        cache_ttl_seconds=settings.prompt_cache_ttl_seconds,
        fallback=SYSTEM_PROMPT_FALLBACK,
    )
