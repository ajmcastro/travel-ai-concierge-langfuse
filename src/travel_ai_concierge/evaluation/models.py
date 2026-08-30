from typing import Any, Literal

from pydantic import BaseModel, Field


class EvaluationCase(BaseModel):
    """One deterministic test case (Milestone 9's dataset schema).

    `expected_arguments` is only checked against the call to
    `expected_tools[0]` — multi-tool cases exist for dataset coverage of the
    "requires multiple tools" query class, but per-argument checking stays
    scoped to the first tool for simplicity (see RATIONALE_PER_MILESTONE.md).
    A `tags` key in `expected_arguments` is checked as "any overlap", not
    exact match; every other key requires exact equality.
    """

    id: str
    query_class: str
    message: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_arguments: dict[str, Any] = Field(default_factory=dict)
    expects_clarification: bool = False


EvaluatorOutcome = Literal["pass", "fail", "skip"]


class EvaluatorResult(BaseModel):
    evaluator: str
    outcome: EvaluatorOutcome
    detail: str = ""


class CaseResult(BaseModel):
    """What actually happened when a case was run through the real agent."""

    case_id: str
    query_class: str
    trace_id: str | None
    tool_calls: list[str]
    tool_arguments_by_name: dict[str, dict[str, Any]]
    tool_result_texts: list[str]
    final_response: str
    iterations: int


class CaseReport(BaseModel):
    case: EvaluationCase
    result: CaseResult
    evaluations: list[EvaluatorResult]
