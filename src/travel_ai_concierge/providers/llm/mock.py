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
    "destination": ("search_destinations", {"tags": ["beach"]}),
}


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
            for keyword, (tool_name, args) in _MOCK_TOOL_TRIGGERS.items():
                if keyword in last_user_message.lower() and tool_name in available:
                    call = ToolCall(
                        id=f"mock-{uuid.uuid4().hex[:8]}", name=tool_name, arguments=args
                    )
                    return "", [call]

        return f"[mock] I heard: {last_user_message}", []
