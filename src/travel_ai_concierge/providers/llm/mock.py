import uuid

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, ToolCall, ToolSpec, Usage

MODEL_NAME = "mock-echo-v1"

# Deterministic stand-in for real reasoning: a keyword -> (tool, fixed args)
# trigger table. This is a test double, not a planner — its only job is to
# let the agent loop (Milestone 5) be exercised offline, deterministically,
# without a paid LLM API. Real tool selection is the LLM's job in
# AnthropicProvider; MockProvider only needs to be *some* deterministic
# decision-maker so tests can assert on the resulting trace shape.
_MOCK_TOOL_TRIGGERS: dict[str, tuple[str, dict[str, object]]] = {
    "hotel": ("search_hotels", {"destination_id": "algarve", "family_friendly": True}),
}

# Milestone 16: words that suggest the user wants a destination search.
# Broadened from a single literal "destination" match (M1-M15) to also catch
# "trip" — a real, deliberately-introduced regression: someone trying to fix
# a failing eval case (culture-001, "I want a trip full of culture...") added
# "trip" as a second trigger, copy-pasting the "destination" trigger's fixed
# tags=["beach"] verbatim. That made the case pass, but it also silently
# fired on vague-request-002 ("Help me plan a trip.") — a case that expects a
# clarifying question with NO tool call. Diagnosed from a real Langfuse trace
# (the `llm_call` generation showed `tool_calls: ['search_destinations']` for
# that message, contradicting the system prompt's own "ask clarifying
# questions when important details are missing" instruction); see
# docs/EXPERIMENTS.md, Milestone 16, for the full before/after evaluation
# numbers. The fix below keeps the broadened trigger words but requires an
# actual content signal (a known interest tag) before firing at all, instead
# of assuming "trip"/"destination" alone always means "search now."
_DESTINATION_TRIGGER_WORDS = ("destination", "trip")

# Same tag vocabulary `TOOL_SPECS` documents for `search_destinations`
# (Milestone 1) — used here as a deterministic, offline proxy for "does this
# message actually express a concrete preference," not just a name that
# happens to include the word "trip" or "destination".
_KNOWN_TAGS = (
    "beach",
    "culture",
    "quiet",
    "food",
    "nightlife",
    "nature",
    "romantic",
    "family",
    "adventure",
    "wine",
)


class MockProvider:
    """Deterministic, offline provider — no network, no credentials.

    Still opens a real Langfuse `generation` span, with the same shape a real
    provider would produce (model, input, output, usage), so a trace looks
    structurally identical whether `LLM_PROVIDER=mock` or `=anthropic`. Token
    counts are a word-count stand-in, not a real tokenizer — good enough to
    exercise cost/latency dashboards without needing `tiktoken` for a model
    family that doesn't even use it.
    """

    model = MODEL_NAME

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=self.model,
            input=[m.model_dump() for m in messages],
        ) as generation:
            # Milestone 15: same reasoning as AnthropicProvider's own
            # try/except — `_decide()` can't currently raise on its own, but
            # a `FaultInjectingProvider` wrapping this one (llm_malformed_output)
            # still calls through to real MockProvider.complete() first, so
            # keeping both providers' error-marking behavior identical matters
            # for a consistent demo — see faults.py and docs/DEBUGGING_WORKFLOWS.md.
            try:
                content, tool_calls = self._decide(messages, tools)
            except Exception as exc:
                generation.update(level="ERROR", status_message=str(exc))
                raise

            usage = Usage(
                input_tokens=sum(len(m.content.split()) for m in messages),
                output_tokens=len(content.split()) if content else 1,
            )
            generation.update(
                output=content or f"[tool_calls: {[tc.name for tc in tool_calls]}]",
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
            )

        return LLMResponse(content=content, model=self.model, usage=usage, tool_calls=tool_calls)

    def _decide(
        self, messages: list[Message], tools: list[ToolSpec] | None
    ) -> tuple[str, list[ToolCall]]:
        # A tool result is already in the conversation — synthesize a final
        # answer from it rather than calling another tool, so the mock loop
        # terminates after exactly one tool round-trip.
        if messages and messages[-1].role == "tool":
            return f"[mock] Based on the tool result: {messages[-1].content}", []

        last_user_message = next((m.content for m in reversed(messages) if m.role == "user"), "")

        if tools:
            available = {t.name for t in tools}
            lowered = last_user_message.lower()

            for keyword, (tool_name, args) in _MOCK_TOOL_TRIGGERS.items():
                if keyword in lowered and tool_name in available:
                    call = ToolCall(
                        id=f"mock-{uuid.uuid4().hex[:8]}", name=tool_name, arguments=args
                    )
                    return "", [call]

            if "search_destinations" in available and any(
                w in lowered for w in _DESTINATION_TRIGGER_WORDS
            ):
                detected_tags = [t for t in _KNOWN_TAGS if t in lowered]
                if detected_tags:
                    call = ToolCall(
                        id=f"mock-{uuid.uuid4().hex[:8]}",
                        name="search_destinations",
                        arguments={"tags": detected_tags},
                    )
                    return "", [call]

        return f"[mock] I heard: {last_user_message}", []
