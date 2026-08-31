"""Milestone 15: controllable fault injection.

Deliberately *not* a global runtime setting (no `FAULT_INJECTION=true` env
var) — that shape of switch is exactly the kind of thing that gets left on
by accident in a real deployment. Every fault here is an explicit wrapper,
swapped in the same scoped, restored-in-a-`finally` way Milestone 14's
`UsageTrackingProvider` already established (a monkey-patch of
`agent.nodes.get_llm_provider`, or a temporary swap of one `TOOL_REGISTRY`
entry) — something a test or a demo script opts into, not something ambient
that could fire in production.

Maps the project spec's own fault list onto the concrete shape each one
takes in *this* architecture, not an abstract simulation:
- "LLM timeout" / "LLM provider unavailable" — the LLM call itself never
  completes. `FaultInjectingProvider` opens its own `llm_call` generation
  span (matching real providers' own instrumentation, per ADR-003 — each
  provider owns its own spans, not a shared helper) and raises before ever
  reaching the wrapped provider.
- "malformed structured response" — this project has no free-form JSON
  parsing step to corrupt; the only structured output an LLM produces here
  is a tool call. `FaultInjectingProvider` calls the *real* wrapped provider
  (so the generation span stays correctly instrumented) and then strips a
  required argument from whatever tool call comes back — reusing Milestone
  6's already-proven missing-argument handling in `agent/nodes.py`'s
  `tools_node`, not inventing a new failure path.
- "travel provider error" / "tool exception" / "tool timeout" —
  `make_failing_tool()` returns a function matching a real tool's calling
  convention that raises immediately. There is no real tool timeout
  mechanism to trigger (today's tools are synchronous local JSON lookups
  with no real latency to time out) — this simulates a tool that detected
  and raised its own timeout, the realistic shape a real HTTP client with a
  configured timeout would take, rather than building generic execution
  preemption for code that has nothing slow to preempt.
"""

from collections.abc import Callable
from typing import Any, Literal

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.base import LLMProvider, LLMResponse, Message, ToolSpec

FaultType = Literal[
    "llm_timeout",
    "llm_provider_unavailable",
    "llm_malformed_output",
    "tool_exception",
    "tool_timeout",
]

_LLM_CALL_FAILURE_EXCEPTIONS: dict[str, type[Exception]] = {
    "llm_timeout": TimeoutError,
    "llm_provider_unavailable": ConnectionError,
}

_TOOL_FAILURE_EXCEPTIONS: dict[str, type[Exception]] = {
    "tool_exception": ConnectionError,
    "tool_timeout": TimeoutError,
}


class FaultInjectingProvider:
    """Wraps any real LLMProvider, deliberately misbehaving per `fault`.

    Only `llm_timeout`/`llm_provider_unavailable`/`llm_malformed_output` are
    valid here — tool faults are a different layer, see `make_failing_tool`.
    """

    def __init__(self, wrapped: LLMProvider, fault: FaultType) -> None:
        if fault not in ("llm_timeout", "llm_provider_unavailable", "llm_malformed_output"):
            raise ValueError(f"{fault!r} is not an LLM-layer fault — use make_failing_tool()")
        self._wrapped = wrapped
        self._fault = fault

    @property
    def model(self) -> str:
        return self._wrapped.model

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        if self._fault == "llm_malformed_output":
            return await self._malformed_output(messages, tools)
        return await self._call_failure(messages)

    async def _call_failure(self, messages: list[Message]) -> LLMResponse:
        exc_type = _LLM_CALL_FAILURE_EXCEPTIONS[self._fault]
        message = f"simulated {self._fault.replace('_', ' ')}"
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="llm_call",
            as_type="generation",
            model=self._wrapped.model,
            input=[m.model_dump() for m in messages],
        ) as generation:
            exc = exc_type(message)
            generation.update(level="ERROR", status_message=str(exc))
            raise exc

    async def _malformed_output(
        self, messages: list[Message], tools: list[ToolSpec] | None
    ) -> LLMResponse:
        response = await self._wrapped.complete(messages, tools=tools)
        if not response.tool_calls:
            # Nothing to corrupt — the wrapped provider didn't request a
            # tool for this message, so there's no structured output to
            # malform. Returning the real response unchanged is more honest
            # than fabricating a tool call the model never asked for.
            return response

        corrupted = response.tool_calls[0].model_copy(update={"arguments": {}})
        return response.model_copy(update={"tool_calls": [corrupted, *response.tool_calls[1:]]})


def make_failing_tool(
    fault: Literal["tool_exception", "tool_timeout"], *, tool_name: str
) -> Callable[..., Any]:
    """Returns a function matching a real tool's calling convention
    (accepts any kwargs, matching how `tools_node` calls `func(**call.arguments)`)
    that raises immediately — for temporarily replacing one `TOOL_REGISTRY`
    entry, not for registering permanently.
    """
    exc_type = _TOOL_FAILURE_EXCEPTIONS[fault]
    message = f"simulated {fault.replace('_', ' ')} in {tool_name!r}"

    def _failing_tool(**kwargs: object) -> None:
        raise exc_type(message)

    _failing_tool.__name__ = f"failing_{tool_name}"
    return _failing_tool
