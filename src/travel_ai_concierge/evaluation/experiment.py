"""Milestone 10: run the evaluation dataset as a Langfuse experiment.

Reuses Milestone 9's evaluators and runner unchanged — this module is only
the adapter layer between our own `EvaluationCase`/`CaseResult`/
`EvaluatorResult` shapes and the SDK's generic `run_experiment()` protocol
(`item.input`/`.expected_output`/`.metadata`, `Evaluation` objects). Verified
against a real local Langfuse instance before writing this for real: nested
tracing inside a `task()` function composes correctly with the SDK's own
dataset-run linking, the same "nesting is free" property established since
Milestone 4 for Langfuse spans generally.

Deliberately not attempting to compute cost/token-usage aggregates here —
Langfuse already captures those natively per generation (unchanged since
Milestone 2) and surfaces them in the dataset run's own comparison view
(`ExperimentResult.dataset_run_url`); recomputing them locally would
duplicate the SDK and require plumbing usage totals through `AgentState`,
well beyond this milestone's actual scope. See
docs/RATIONALE_PER_MILESTONE.md (Milestone 10).
"""

from typing import Any

from langfuse import Evaluation
from langfuse.experiment import EvaluatorFunction, ExperimentResult

from travel_ai_concierge.evaluation.evaluators import EVALUATORS, Evaluator
from travel_ai_concierge.evaluation.judge import get_judge_provider
from travel_ai_concierge.evaluation.langfuse_sync import DATASET_NAME
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase
from travel_ai_concierge.evaluation.runner import run_case
from travel_ai_concierge.evaluation.trajectory import compute_trajectory_metrics
from travel_ai_concierge.observability import get_langfuse_client


def _case_from_parts(
    input_data: dict[str, Any],
    expected_output: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> EvaluationCase:
    expected = expected_output or {}
    meta = metadata or {}
    return EvaluationCase(
        id=meta.get("case_id", "unknown"),
        query_class=meta.get("query_class", "unknown"),
        message=input_data["message"],
        expected_tools=expected.get("expected_tools", []),
        expected_arguments=expected.get("expected_arguments", {}),
        expects_clarification=expected.get("expects_clarification", False),
    )


async def _task(*, item: Any, **kwargs: object) -> dict[str, Any]:
    case = _case_from_parts(item.input, item.expected_output, item.metadata)
    result = await run_case(case)
    return result.model_dump()


def _adapt_evaluator(evaluator: Evaluator) -> EvaluatorFunction:
    """Wrap one Milestone 9 evaluator as a Langfuse EvaluatorFunction.

    Maps pass/fail to a numeric 1.0/0.0 (so the SDK's own `.format()` can
    average it across items automatically) and skip to an empty evaluation
    list (so a not-applicable case is excluded from that average entirely,
    not counted as a failure — same semantics M9 established locally).
    """

    def adapted(
        *, input: Any, output: Any, expected_output: Any, metadata: Any, **kwargs: object
    ) -> list[Evaluation]:
        case = _case_from_parts(input, expected_output, metadata)
        result = CaseResult(**output)
        evaluation = evaluator(case, result)
        if evaluation.outcome == "skip":
            return []
        return [
            Evaluation(
                name=evaluation.evaluator,
                value=1.0 if evaluation.outcome == "pass" else 0.0,
                comment=evaluation.detail or None,
            )
        ]

    adapted.__name__ = evaluator.__name__
    return adapted


def _trajectory_evaluator(
    *, input: Any, output: Any, expected_output: Any, metadata: Any, **kwargs: object
) -> list[Evaluation]:
    """Milestone 13: trajectory.py's metrics, pushed as extra Evaluations on
    the same dataset run — unconditional (like the Layer 1 adapters above),
    not opt-in like `_judge_evaluator`, because it costs nothing extra: no
    LLM call, purely derived from data `_task` already collected.
    `tool_precision` is omitted when `None` (no tool was called at all —
    "precision of zero calls" is undefined, not zero), the same
    skip-rather-than-fail principle `_adapt_evaluator` already uses.
    """
    case = _case_from_parts(input, expected_output, metadata)
    result = CaseResult(**output)
    trajectory = compute_trajectory_metrics(case, result)

    evaluations = [
        Evaluation(name="trajectory_tool_recall", value=trajectory.tool_recall),
        Evaluation(name="trajectory_agent_steps", value=float(trajectory.agent_steps)),
        Evaluation(
            name="trajectory_healthy",
            value=1.0 if trajectory.is_healthy else 0.0,
            comment=(
                f"missing={trajectory.missing_tools}, unnecessary={trajectory.unnecessary_tools}, "
                f"repeated={trajectory.repeated_tools}"
                if not trajectory.is_healthy
                else None
            ),
        ),
    ]
    if trajectory.tool_precision is not None:
        evaluations.append(
            Evaluation(name="trajectory_tool_precision", value=trajectory.tool_precision)
        )
    return evaluations


async def _judge_evaluator(
    *, input: Any, output: Any, expected_output: Any, metadata: Any, **kwargs: object
) -> list[Evaluation]:
    """Milestone 11: the same JudgeProvider used by run_evaluation.py's
    `--with-judge`, wrapped for run_experiment() — one Evaluation per
    dimension, prefixed `judge_` so they're visually distinct from Layer 1's
    deterministic scores in the same dataset run.
    """
    case = _case_from_parts(input, expected_output, metadata)
    result = CaseResult(**output)
    judgments = await get_judge_provider().judge(case, result)
    return [
        Evaluation(name=f"judge_{j.dimension}", value=j.score, comment=j.rationale)
        for j in judgments
    ]


def run_named_experiment(
    *,
    run_name: str,
    description: str | None = None,
    dataset_name: str = DATASET_NAME,
    with_judge: bool = False,
) -> ExperimentResult:
    client = get_langfuse_client()
    dataset = client.get_dataset(dataset_name)
    evaluators: list[EvaluatorFunction] = [_adapt_evaluator(evaluator) for evaluator in EVALUATORS]
    evaluators.append(_trajectory_evaluator)
    if with_judge:
        evaluators.append(_judge_evaluator)
    result = dataset.run_experiment(
        name="Travel Concierge Evaluation",
        run_name=run_name,
        description=description,
        task=_task,
        evaluators=evaluators,
    )
    client.flush()
    return result
