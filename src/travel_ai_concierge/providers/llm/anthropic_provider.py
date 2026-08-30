from typing import Any

from anthropic import AsyncAnthropic

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, ToolCall, ToolSpec, Usage


def _to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate our provider-agnostic Message list into Anthropic's shape.

    Verified against the installed SDK's types rather than assumed:
    - assistant tool calls -> content blocks of type "tool_use"
      (anthropic.types.tool_use_block_param.ToolUseBlockParam)
    - a tool result -> Anthropic has no "tool" role; it must be a *user*
      message with a "tool_result" content block
      (anthropic.types.tool_result_block_param.ToolResultBlockParam)
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "assistant" and m.tool_calls:
            content: list[dict[str, Any]] = []
            if m.content:
                content.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                )
            result.append({"role": "assistant", "content": content})
        elif m.role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id,
                            "content": m.content,
                        }
                    ],
                }
            )
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def _to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


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

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        system_prompt = next((m.content for m in messages if m.role == "system"), "")
        conversation = _to_anthropic_messages(messages)

        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=self.model,
            input=[m.model_dump() for m in messages],
            model_parameters={"max_tokens": self.max_tokens},
        ) as generation:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system_prompt,
                "messages": conversation,
            }
            if tools:
                kwargs["tools"] = _to_anthropic_tools(tools)

            response = await self._client.messages.create(**kwargs)

            text = "".join(block.text for block in response.content if block.type == "text")
            tool_calls = [
                ToolCall(id=block.id, name=block.name, arguments=block.input)
                for block in response.content
                if block.type == "tool_use"
            ]
            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            generation.update(
                output=text or f"[tool_calls: {[tc.name for tc in tool_calls]}]",
                usage_details={"input": usage.input_tokens, "output": usage.output_tokens},
            )

        return LLMResponse(content=text, model=response.model, usage=usage, tool_calls=tool_calls)
