"""Milestone 11: LLM-as-judge (Layer 2 evaluation).

Layer 1 (Milestone 9's deterministic evaluators) answers mechanical
questions — was this tool called, did these arguments match. Some questions
aren't mechanical: is this response actually *helpful*, does it stay
*grounded* in what the tools returned, is a proposed itinerary internally
*coherent*. Those need a judge, not a rule.

## Documented limitations (the spec requires this explicitly)

- **Not an independent model family.** The spec: "prefer an independent
  judge model family when possible." This project has exactly one real LLM
  vendor (`AnthropicProvider` — OpenAI is listed as "planned" in the
  README's own Technology table but was never built). `AnthropicJudgeProvider`
  is Anthropic judging Anthropic's own output family — a real, unaddressed
  methodological weakness, not something this milestone solves. Partial
  mitigation: `Settings.judge_model` is independently configurable from
  `Settings.llm_model`, so at minimum a different capability tier can judge,
  which reduces (does not eliminate) self-preference risk.
- **Self-preference / verbosity bias.** LLM judges are documented in the
  evaluation literature to rate their own model family's outputs more
  favorably, and to rate longer, more effusive answers higher regardless of
  actual quality. Neither is controlled for here.
- **Stochasticity.** `AnthropicProvider.complete()` never sends `temperature`
  at all (the installed SDK version has no such parameter — see M2's own
  finding) — there is no way to force determinism, and no reason to assume
  identical inputs produce identical scores across repeated runs. Not
  verified live in this environment (no `ANTHROPIC_API_KEY` configured);
  see `tests/integration/test_llm_judge.py`.
- **Judged on the conversation alone, not our own ground truth.** The judge
  sees the user's message, the agent's final response, and the raw tool
  results — never this project's own `EvaluationCase.expected_tools`/
  `expected_arguments` test fixtures. That comparison is Layer 1's job
  already; showing the judge our own answer key would make "constraint
  satisfaction" a check against our test data instead of an independent
  read of the conversation.
- **`FakeJudgeProvider` is not a stand-in for judgment.** It derives scores
  deterministically from Milestone 9's own evaluator outcomes (documented
  per-score in its rationale) purely so the judge *interface* — and
  everything built against it — is testable without cost, latency, or
  nondeterminism. It answers no question a real judge is asked to answer.
"""

import json
from functools import lru_cache
from typing import Protocol

from langfuse import propagate_attributes
from pydantic import BaseModel

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation.evaluators import (
    evaluate_groundedness_proxy,
    evaluate_response_nonempty,
    evaluate_tool_arguments,
    evaluate_tool_usage,
)
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm.anthropic_provider import AnthropicProvider
from travel_ai_concierge.providers.llm.base import Message

DIMENSION_DEFINITIONS: dict[str, str] = {
    "relevance": "Does the response actually address what the user asked?",
    "helpfulness": "Would a real traveller find this response useful and actionable?",
    "groundedness": (
        "Are specific facts in the response (hotel names, prices, destinations) actually "
        "supported by the tool results provided, not invented?"
    ),
    "constraint_satisfaction": (
        "Does the response respect constraints stated in the user's own message "
        "(budget, family-friendliness, destination, etc.)?"
    ),
    "itinerary_coherence": (
        "Is any proposed itinerary or day-by-day plan internally consistent and logically ordered?"
    ),
}

SCORE_SCALE = "1=poor, 2=weak, 3=acceptable, 4=good, 5=excellent"

JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluator scoring an AI travel concierge's response. "
    f"Score each requested dimension from 1 to 5 ({SCORE_SCALE}). "
    'Respond with ONLY a JSON object of the exact shape {"judgments": '
    '[{"dimension": "...", "score": N, "rationale": "..."}]}, one entry per requested '
    "dimension, rationale under 30 words. No text outside the JSON object."
)


def _applicable_dimensions(case: EvaluationCase) -> list[str]:
    dimensions = ["relevance", "helpfulness", "groundedness", "constraint_satisfaction"]
    if case.query_class == "itinerary_planning":
        dimensions.append("itinerary_coherence")
    return dimensions


class JudgmentResult(BaseModel):
    dimension: str
    score: int
    rationale: str


class JudgeProvider(Protocol):
    model: str

    async def judge(self, case: EvaluationCase, result: CaseResult) -> list[JudgmentResult]: ...


class JudgeParseError(Exception):
    """The judge's response couldn't be trusted as a real score.

    Deliberately not caught and silently coerced into a fallback score
    anywhere in this module — "do not blindly trust LLM-as-judge scores"
    (spec) applies just as much to a broken parse as to a suspicious one.
    """


class FakeJudgeProvider:
    """Deterministic, offline, free — see this module's own docstring for
    why this exists and what it does *not* claim to answer.
    """

    model = "fake-judge-v1"

    async def judge(self, case: EvaluationCase, result: CaseResult) -> list[JudgmentResult]:
        client = get_langfuse_client()
        dimensions = _applicable_dimensions(case)

        with client.start_as_current_observation(
            name="llm_judge",
            as_type="evaluator",
            input={"case_id": case.id, "dimensions": dimensions},
        ) as span:
            tool_usage = evaluate_tool_usage(case, result)
            groundedness = evaluate_groundedness_proxy(case, result)
            constraints = evaluate_tool_arguments(case, result)
            nonempty = evaluate_response_nonempty(case, result)

            scores = {
                "relevance": 5
                if nonempty.outcome == "pass" and tool_usage.outcome != "fail"
                else 2,
                "helpfulness": 5 if nonempty.outcome == "pass" else 1,
                "groundedness": 5 if groundedness.outcome != "fail" else 1,
                "constraint_satisfaction": 5 if constraints.outcome != "fail" else 2,
                "itinerary_coherence": 3,
            }
            judgments = [
                JudgmentResult(
                    dimension=dimension,
                    score=scores[dimension],
                    rationale=(
                        "Deterministic fake judge — itinerary coherence cannot be assessed "
                        "without real language understanding; fixed neutral score."
                        if dimension == "itinerary_coherence"
                        else (
                            "Deterministic fake judge — derived from Milestone 9's own "
                            f"'{tool_usage.evaluator}' ({tool_usage.outcome}), "
                            f"'{groundedness.evaluator}' ({groundedness.outcome}), "
                            f"'{constraints.evaluator}' ({constraints.outcome}) signals, "
                            "not real language understanding."
                        )
                    ),
                )
                for dimension in dimensions
            ]
            span.update(output={"judgments": [j.model_dump() for j in judgments]})

        return judgments


def _build_judge_user_message(
    case: EvaluationCase, result: CaseResult, dimensions: list[str]
) -> str:
    lines = [
        f"User message: {case.message}",
        f"Agent's final response: {result.final_response}",
    ]
    if result.tool_result_texts:
        lines.append("Tool results the agent had access to:")
        lines.extend(f"- {text}" for text in result.tool_result_texts)
    else:
        lines.append("The agent called no tools for this turn.")

    lines.append("Score exactly these dimensions:")
    lines.extend(f"- {dimension}: {DIMENSION_DEFINITIONS[dimension]}" for dimension in dimensions)
    return "\n".join(lines)


def _parse_judgments(text: str, expected_dimensions: list[str]) -> list[JudgmentResult]:
    try:
        data = json.loads(text)
        raw_judgments = data["judgments"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise JudgeParseError(
            f"Judge response was not valid JSON with a 'judgments' key: {text!r}"
        ) from exc

    judgments = []
    for item in raw_judgments:
        dimension = item.get("dimension")
        score = item.get("score")
        if dimension not in expected_dimensions:
            continue  # ignore a hallucinated/extra dimension rather than fail the whole judgment
        if not isinstance(score, int) or not (1 <= score <= 5):
            raise JudgeParseError(
                f"Judge returned an out-of-range score for {dimension!r}: {score!r}"
            )
        judgments.append(
            JudgmentResult(
                dimension=dimension, score=score, rationale=str(item.get("rationale", ""))
            )
        )

    missing = set(expected_dimensions) - {j.dimension for j in judgments}
    if missing:
        raise JudgeParseError(f"Judge response is missing dimension(s): {sorted(missing)}")

    return judgments


class AnthropicJudgeProvider:
    """A real LLM call scoring one case — one call returns every applicable
    dimension's score, not one call per dimension (cost/latency).
    """

    def __init__(
        self, api_key: str, model: str, max_tokens: int = 1024, timeout: float = 30.0
    ) -> None:
        self.model = model
        self._provider = AnthropicProvider(
            api_key=api_key, model=model, max_tokens=max_tokens, timeout=timeout
        )

    async def judge(self, case: EvaluationCase, result: CaseResult) -> list[JudgmentResult]:
        client = get_langfuse_client()
        dimensions = _applicable_dimensions(case)
        messages = [
            Message(role="system", content=JUDGE_SYSTEM_PROMPT),
            Message(role="user", content=_build_judge_user_message(case, result, dimensions)),
        ]

        # as_type="evaluator": a real, distinct Langfuse observation type
        # (verified via SDK introspection, same principle as `tool`/`agent`
        # since M4/M5) — not linked to the original case's trace (that would
        # need cross-trace parent-span linking); `judged_trace_id` in
        # metadata records the connection instead, a deliberate simplicity
        # trade-off over true nesting.
        with client.start_as_current_observation(
            name="llm_judge",
            as_type="evaluator",
            input={"case_id": case.id, "dimensions": dimensions},
        ) as span:
            with propagate_attributes(
                tags=["judge", case.query_class],
                metadata={"case_id": case.id, "judged_trace_id": result.trace_id},
            ):
                response = await self._provider.complete(messages)

            judgments = _parse_judgments(response.content, dimensions)
            span.update(output={"judgments": [j.model_dump() for j in judgments]})

        return judgments


@lru_cache(maxsize=1)
def get_judge_provider() -> JudgeProvider:
    settings = get_settings()
    if settings.judge_provider == "fake":
        return FakeJudgeProvider()
    return AnthropicJudgeProvider(
        api_key=settings.anthropic_api_key,
        model=settings.judge_model,
        max_tokens=1024,
        timeout=settings.llm_timeout_seconds,
    )
