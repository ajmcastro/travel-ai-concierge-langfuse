"""Milestone 14: cost and latency measurement, purely local.

Langfuse already captures token usage, latency, and cost per generation
natively (unchanged since Milestone 2) — but this deployment runs Langfuse
v4 "events_only" mode, which disables the public read API entirely (see
docs/langfuse.md). We can *write* that data to Langfuse, but we can't read
it back programmatically to build a side-by-side comparison. So this module
measures the same things a different way: `LLMResponse.usage` and wall-clock
timing around `provider.complete()` are both available in-process, before
anything is ever sent to Langfuse at all — this isn't blocked by
events_only mode, since it never needs Langfuse's read API.

`UsageTrackingProvider` wraps any real `LLMProvider` and records each call
as a side effect, without changing what gets sent to the model or what
Langfuse itself records — the wrapped provider's own `complete()` still
opens its own `llm_call` generation span exactly as before.
"""

import time

from pydantic import BaseModel

import travel_ai_concierge.agent.nodes as agent_nodes
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase
from travel_ai_concierge.evaluation.runner import run_case
from travel_ai_concierge.providers.llm.base import LLMProvider, LLMResponse, Message, ToolSpec

# Illustrative, approximate USD-per-million-token rates, keyed by a
# case-insensitive substring of the model name (real model IDs drift
# version-to-version, e.g. "claude-sonnet-4-5" vs "claude-sonnet-5" — a
# substring match on the tier name is more durable than an exact string).
# NOT independently verified against Anthropic's live pricing page — for
# exercising the cost-calculation mechanism, not for real budget decisions.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "haiku": (0.80, 4.00),
    "sonnet": (3.00, 15.00),
    "opus": (15.00, 75.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """`None` when the model isn't in MODEL_PRICING — e.g. MockProvider's
    "mock-echo-v1" has no real inference cost at all, not an unknown price.
    """
    model_lower = model.lower()
    for tier, (input_rate, output_rate) in MODEL_PRICING.items():
        if tier in model_lower:
            return (input_tokens / 1_000_000) * input_rate + (
                output_tokens / 1_000_000
            ) * output_rate
    return None


class LLMCallMetrics(BaseModel):
    input_tokens: int
    output_tokens: int
    latency_ms: float


class UsageTrackingProvider:
    """Wraps any LLMProvider, recording each call's usage + wall-clock
    latency. Delegates `.complete()` unchanged — Langfuse tracing inside the
    wrapped provider is untouched; this only observes the return value.
    """

    def __init__(self, wrapped: LLMProvider) -> None:
        self._wrapped = wrapped
        self.calls: list[LLMCallMetrics] = []

    @property
    def model(self) -> str:
        return self._wrapped.model

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        start = time.monotonic()
        response = await self._wrapped.complete(messages, tools=tools)
        latency_ms = (time.monotonic() - start) * 1000
        self.calls.append(
            LLMCallMetrics(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
            )
        )
        return response


class CaseCostLatency(BaseModel):
    case_id: str
    query_class: str
    llm_call_count: int
    total_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float | None


async def run_case_with_metrics(
    case: EvaluationCase, *, config_name: str | None = None
) -> tuple[CaseResult, CaseCostLatency]:
    """Runs one case through the real agent graph (`run_case()`, unchanged)
    while a `UsageTrackingProvider` stands in for the real provider.

    Patches `agent.nodes.get_llm_provider` directly (the same single import
    site the project's own tests patch — see test_trace_design.py) rather
    than threading a provider parameter through `run_case()`/`agent_node()`,
    which would touch the core, heavily-tested agent graph for a milestone
    that doesn't need to change its behavior, only observe it. Restored in
    a `finally` immediately after this one case, not held across a whole
    dataset run, so a crash mid-loop can't leave the patch installed.
    `type: ignore[attr-defined]` on the two assignments below: `nodes.py`
    imports `get_llm_provider` without re-exporting it, so mypy treats
    reassigning it here as touching an attribute the module doesn't
    officially expose — true, and exactly the point (this is a deliberate
    monkey-patch of that import site, the same one the tests patch via
    `monkeypatch.setattr("...get_llm_provider", ...)` by string instead).

    `config_name`, when given, is passed through to `run_case()`'s own
    `extra_tags`/`extra_metadata` — so the resulting trace is filterable in
    Langfuse's UI by which configuration produced it, closing the gap
    documented in RATIONALE_PER_MILESTONE.md's Milestone 14 entry (the
    traces originally carried no config-identifying data at all).
    """
    original_get_llm_provider = agent_nodes.get_llm_provider  # type: ignore[attr-defined]
    tracker = UsageTrackingProvider(original_get_llm_provider())
    agent_nodes.get_llm_provider = lambda: tracker  # type: ignore[attr-defined, assignment]
    try:
        result = await run_case(
            case,
            extra_tags=["cost-latency-experiment", config_name] if config_name else None,
            extra_metadata={"cost_latency_config": config_name} if config_name else None,
        )
    finally:
        agent_nodes.get_llm_provider = original_get_llm_provider  # type: ignore[attr-defined]

    total_input = sum(c.input_tokens for c in tracker.calls)
    total_output = sum(c.output_tokens for c in tracker.calls)
    cost_latency = CaseCostLatency(
        case_id=case.id,
        query_class=case.query_class,
        llm_call_count=len(tracker.calls),
        total_latency_ms=sum(c.latency_ms for c in tracker.calls),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        estimated_cost_usd=estimate_cost_usd(tracker.model, total_input, total_output)
        if tracker.calls
        else None,
    )
    return result, cost_latency
