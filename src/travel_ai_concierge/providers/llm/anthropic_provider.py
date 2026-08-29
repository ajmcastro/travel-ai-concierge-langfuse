from anthropic import AsyncAnthropic

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, Usage


class AnthropicProvider:
    """Real LLM provider backed by the Anthropic Messages API.

    Note: this SDK version's `messages.create()` has no `temperature`
    parameter — verified by introspecting the installed `anthropic` package
    rather than assuming the older API shape (see docs/EXPERIMENTS.md,
    Milestone 2). `Settings.llm_temperature` is kept for providers that do
    support it; it is silently unused here.
    """

    def __init__(self, api_key: str, model: str, max_tokens: int, timeout: float) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)

    async def complete(self, messages: list[Message]) -> LLMResponse:
        system_prompt = next((m.content for m in messages if m.role == "system"), "")
        conversation = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]

        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=self.model,
            input=[m.model_dump() for m in messages],
            model_parameters={"max_tokens": self.max_tokens},
        ) as generation:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=conversation,  # type: ignore[arg-type]
            )

            text = "".join(block.text for block in response.content if block.type == "text")
            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            generation.update(
                output=text,
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
            )

        return LLMResponse(content=text, model=response.model, usage=usage)
