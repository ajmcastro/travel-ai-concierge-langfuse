# ADR-003: LLM Provider Abstraction

**Date:** 2026-08-28  
**Status:** Accepted

## Context

The application must call a real LLM in production and a deterministic fake in tests — without changing agent logic. We also want Langfuse to capture full generation metadata (model, provider, tokens, latency, cost) for every LLM call.

## Options

### Option A — LangChain LLM abstractions

Use `langchain_anthropic.ChatAnthropic` or `langchain_openai.ChatOpenAI`.

**Cons:** LangChain's callback system makes Langfuse instrumentation less transparent (callbacks fire inside the library, not in our code). Adds LangChain as a heavy dependency. Obscures what is actually sent to the provider.

### Option B — Direct SDK calls, no abstraction

Import `anthropic` or `openai` directly everywhere.

**Cons:** Tests require API credentials. Switching providers requires touching every call site.

### Option C — Protocol-based thin abstraction

Define a `LLMProvider` Protocol with concrete implementations.

```python
class LLMProvider(Protocol):
    async def complete(self, messages: list[Message], **kwargs) -> LLMResponse: ...
```

**Pros:**  
- Tests use `MockProvider` — deterministic, offline, no credentials.  
- Langfuse generation tracking lives *inside* each concrete provider, so model/token/cost metadata is always captured at the right level.  
- Swapping providers is one configuration change.  
- The abstraction is thin enough that developers can read it and immediately understand what is happening.

## Decision

**Protocol-based thin abstraction (Option C)**

The Langfuse instrumentation (`langfuse.generation(...)`) happens inside `AnthropicProvider.complete()`, not behind the Protocol. This keeps the observability explicit — a developer can find the Langfuse call and understand exactly what is being recorded.

## Consequences

- `MockProvider` returns scripted responses for offline testing.
- `AnthropicProvider` (Milestone 2) wraps the `anthropic` SDK and records a Langfuse generation for every call.
- `OpenAIProvider` can be added later with the same interface.
- The Protocol is defined in `src/travel_ai_concierge/providers/llm/base.py` (Milestone 2).
- Model IDs, temperature, and timeouts come from `Settings` — never hardcoded.
- **Milestone 5**: the sketched `**kwargs` became a concrete `tools: list[ToolSpec] | None = None` parameter, and `LLMResponse` gained `tool_calls`. The instrumentation-lives-inside-the-provider decision paid off directly here — `AnthropicProvider` translates our provider-agnostic tool/message shapes into Anthropic's actual API shapes internally (verified via SDK introspection), and that translation logic is exactly as visible and unit-testable as the rest of the provider, not hidden behind the Protocol.
