from typing import Literal, Protocol

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    role: Role
    content: str


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: Usage


class LLMProvider(Protocol):
    """A provider of LLM completions.

    Concrete implementations (MockProvider, AnthropicProvider) are responsible
    for their own Langfuse `generation` instrumentation — see ADR-003. This
    keeps the abstraction thin: swapping providers is a one-line config
    change, but a developer reading a provider's `complete()` method sees
    exactly what gets sent to the model and exactly what gets recorded.
    """

    async def complete(self, messages: list[Message]) -> LLMResponse: ...
