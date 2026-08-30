from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolSpec(BaseModel):
    """A tool definition offered to the LLM — provider-agnostic.

    `input_schema` is a plain JSON Schema dict (`{"type": "object",
    "properties": {...}}`), the format Anthropic's `tools` parameter expects
    directly (verified via `anthropic.types.tool_param.ToolParam`,
    Milestone 5) — no translation needed for that field specifically.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


class Message(BaseModel):
    role: Role
    content: str = ""
    # Only set on an assistant message that requested tool calls.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Only set on a role="tool" message: which call this responds to, and
    # which tool produced it.
    tool_call_id: str | None = None
    name: str | None = None


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: Usage
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMProvider(Protocol):
    """A provider of LLM completions.

    Concrete implementations (MockProvider, AnthropicProvider) are responsible
    for their own Langfuse `generation` instrumentation — see ADR-003. This
    keeps the abstraction thin: swapping providers is a one-line config
    change, but a developer reading a provider's `complete()` method sees
    exactly what gets sent to the model and exactly what gets recorded.
    """

    model: str

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse: ...
