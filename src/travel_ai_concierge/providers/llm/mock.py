from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, Usage

MODEL_NAME = "mock-echo-v1"


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

    async def complete(self, messages: list[Message]) -> LLMResponse:
        last_user_message = next((m.content for m in reversed(messages) if m.role == "user"), "")
        content = f"[mock] I heard: {last_user_message}"

        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=self.model,
            input=[m.model_dump() for m in messages],
        ) as generation:
            usage = Usage(
                input_tokens=sum(len(m.content.split()) for m in messages),
                output_tokens=len(content.split()),
            )
            # Langfuse's recognized usage_details keys are "input"/"output"
            # (verified in the Milestone 1 smoke test's UI rendering) — kept
            # separate from our own domain field names (`input_tokens` etc.).
            generation.update(
                output=content,
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
            )

        return LLMResponse(content=content, model=self.model, usage=usage)
