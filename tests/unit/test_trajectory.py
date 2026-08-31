"""Unit tests for Milestone 13's trajectory metrics and the final-answer vs.
trajectory comparison, fully offline — same discipline as
tests/unit/test_evaluators.py: every case is a hand-built EvaluationCase/
CaseResult, not a real agent/MockProvider run, so these test the metric
*logic* in isolation from what MockProvider happens to be capable of.
"""

from travel_ai_concierge.evaluation.models import (
    CaseReport,
    CaseResult,
    EvaluationCase,
    EvaluatorResult,
)
from travel_ai_concierge.evaluation.trajectory import compute_trajectory_metrics
from travel_ai_concierge.evaluation.trajectory_report import (
    build_trajectory_reports,
    classify_divergence,
    compute_quality_metrics,
    final_answer_is_healthy,
    render_trajectory_summary,
    summarize_trajectories,
)


def _case(**kwargs) -> EvaluationCase:
    defaults = {"id": "case-1", "query_class": "test", "message": "hello"}
    return EvaluationCase(**{**defaults, **kwargs})


def _result(**kwargs) -> CaseResult:
    defaults = {
        "case_id": "case-1",
        "query_class": "test",
        "trace_id": "trace-1",
        "tool_calls": [],
        "tool_arguments_by_name": {},
        "tool_result_texts": [],
        "final_response": "some response",
        "iterations": 1,
    }
    return CaseResult(**{**defaults, **kwargs})


# --- compute_trajectory_metrics: tool selection ---


def test_exact_match_is_healthy_with_perfect_precision_and_recall():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.missing_tools == []
    assert metrics.unnecessary_tools == []
    assert metrics.repeated_tools == []
    assert metrics.tool_precision == 1.0
    assert metrics.tool_recall == 1.0
    assert metrics.correct_tool_selection is True
    assert metrics.is_healthy is True


def test_missing_tool_hurts_recall_not_precision():
    case = _case(expected_tools=["search_hotels", "search_destinations"])
    result = _result(tool_calls=["search_hotels"])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.missing_tools == ["search_destinations"]
    assert metrics.unnecessary_tools == []
    assert metrics.tool_precision == 1.0
    assert metrics.tool_recall == 0.5
    assert metrics.correct_tool_selection is False
    assert metrics.is_healthy is False


def test_unnecessary_tool_hurts_precision_not_recall():
    case = _case(expected_tools=[])
    result = _result(tool_calls=["search_hotels"])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.unnecessary_tools == ["search_hotels"]
    assert metrics.missing_tools == []
    assert metrics.tool_precision == 0.0
    assert metrics.tool_recall == 1.0  # nothing expected, so nothing was missed
    assert metrics.is_healthy is False


def test_repeated_tool_call_flags_repeated_but_not_precision_or_recall():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels", "search_hotels"])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.total_tool_calls == 2
    assert metrics.unique_tools_called == ["search_hotels"]
    assert metrics.repeated_tools == ["search_hotels"]
    assert metrics.correct_tool_selection is True  # the *set* is still right
    assert metrics.tool_precision == 1.0
    assert metrics.tool_recall == 1.0
    assert metrics.is_healthy is False  # but the trajectory itself is not


def test_precision_is_none_when_no_tool_was_called_at_all():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=[])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.tool_precision is None  # undefined, not zero
    assert metrics.tool_recall == 0.0
    assert metrics.missing_tools == ["search_hotels"]


def test_agent_steps_is_the_raw_iteration_count():
    case = _case()
    result = _result(iterations=3)
    assert compute_trajectory_metrics(case, result).agent_steps == 3


# --- compute_trajectory_metrics: clarification, both directions ---


def test_asking_a_question_when_not_expected_is_flagged_unnecessary():
    case = _case(expects_clarification=False)
    result = _result(final_response="Budget or luxury?", tool_calls=[])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.asked_unnecessary_clarification is True
    assert metrics.failed_to_clarify_when_expected is False
    assert metrics.is_healthy is False


def test_answering_directly_when_not_expected_is_healthy():
    case = _case(expects_clarification=False)
    result = _result(final_response="Here you go.", tool_calls=[])
    metrics = compute_trajectory_metrics(case, result)
    assert metrics.asked_unnecessary_clarification is False


def test_failing_to_ask_when_expected_is_flagged():
    case = _case(expects_clarification=True)
    result = _result(final_response="Sure, here's an answer.", tool_calls=[])
    metrics = compute_trajectory_metrics(case, result)

    assert metrics.failed_to_clarify_when_expected is True
    assert metrics.is_healthy is False


def test_asking_when_expected_is_healthy():
    case = _case(expects_clarification=True)
    result = _result(final_response="Which city did you have in mind?", tool_calls=[])
    metrics = compute_trajectory_metrics(case, result)
    assert metrics.failed_to_clarify_when_expected is False


# --- final_answer_is_healthy / classify_divergence ---


def test_final_answer_is_healthy_ignores_tool_selection_evaluators():
    # tool_usage_matches_expected is NOT a final-answer evaluator — a failed
    # trajectory must not, by itself, make the answer axis unhealthy.
    evaluations = [
        EvaluatorResult(evaluator="tool_usage_matches_expected", outcome="fail"),
        EvaluatorResult(evaluator="response_is_nonempty", outcome="pass"),
    ]
    assert final_answer_is_healthy(evaluations) is True


def test_final_answer_is_healthy_treats_skip_as_healthy():
    evaluations = [EvaluatorResult(evaluator="response_references_tool_result", outcome="skip")]
    assert final_answer_is_healthy(evaluations) is True


def test_final_answer_is_unhealthy_on_a_real_text_quality_failure():
    evaluations = [EvaluatorResult(evaluator="response_is_nonempty", outcome="fail")]
    assert final_answer_is_healthy(evaluations) is False


def test_good_answer_poor_trajectory_is_the_live_requires_clarification_002_shape():
    # Mirrors the real dataset case: MockProvider calls an unnecessary tool
    # (no clarification expected... here, clarification WAS expected and
    # skipped) but the resulting text is non-empty and references the tool
    # result, so the answer axis reads healthy while the trajectory axis
    # does not — exactly the spec's "good answer != good trajectory".
    case = _case(expected_tools=[], expects_clarification=True)
    result = _result(
        tool_calls=["search_hotels"], final_response="[mock] Based on the tool result: [...]"
    )
    trajectory = compute_trajectory_metrics(case, result)
    evaluations = [
        EvaluatorResult(evaluator="response_is_nonempty", outcome="pass"),
        EvaluatorResult(evaluator="response_references_tool_result", outcome="pass"),
        EvaluatorResult(evaluator="tool_usage_matches_expected", outcome="fail"),
    ]

    assert classify_divergence(evaluations, trajectory) == "good_answer_poor_trajectory"


def test_poor_answer_good_trajectory_is_a_hand_built_synthetic_example():
    # This quadrant cannot occur with MockProvider (see
    # trajectory_report.render_trajectory_summary's own note and
    # docs/RATIONALE_PER_MILESTONE.md, Milestone 13) — MockProvider's text
    # is always derived from whatever it just did, so a correct trajectory
    # can never pair with unhealthy output text under Mock. This fixture
    # constructs the case by hand instead: the agent called exactly the
    # right tool, once, with no unnecessary clarification — but the final
    # text it produced is empty, a genuine answer-quality failure a
    # trajectory check alone would never catch.
    case = _case(expected_tools=["search_hotels"], expects_clarification=False)
    result = _result(tool_calls=["search_hotels"], final_response="")
    trajectory = compute_trajectory_metrics(case, result)
    assert trajectory.is_healthy is True  # the path taken was exactly right

    evaluations = [EvaluatorResult(evaluator="response_is_nonempty", outcome="fail")]

    assert classify_divergence(evaluations, trajectory) == "poor_answer_good_trajectory"


def test_aligned_when_both_axes_agree():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"], final_response="Here are some hotels.")
    trajectory = compute_trajectory_metrics(case, result)
    evaluations = [EvaluatorResult(evaluator="response_is_nonempty", outcome="pass")]

    assert classify_divergence(evaluations, trajectory) == "aligned"


# --- build_trajectory_reports / summarize / render: smoke tests ---


def test_build_and_summarize_and_render_round_trip():
    case = _case(id="c1", expected_tools=["search_hotels"])
    result = _result(
        case_id="c1", tool_calls=["search_hotels"], final_response="Here are some hotels."
    )
    report = CaseReport(
        case=case,
        result=result,
        evaluations=[EvaluatorResult(evaluator="response_is_nonempty", outcome="pass")],
    )

    trajectory_reports = build_trajectory_reports([report])
    assert len(trajectory_reports) == 1
    assert trajectory_reports[0].case_id == "c1"
    assert trajectory_reports[0].divergence == "aligned"

    summary = summarize_trajectories(trajectory_reports)
    assert summary["total_cases"] == 1
    assert summary["divergence_counts"]["aligned"] == 1

    rendered = render_trajectory_summary(trajectory_reports, summary)
    assert "Agent Trajectory Evaluation" in rendered
    assert "aligned" in rendered


def test_summarize_handles_no_precision_data_gracefully():
    # Every case called zero tools — average_tool_precision must not divide
    # by zero, same "None means not applicable" convention as a single
    # case's own tool_precision.
    case = _case(expected_tools=[])
    result = _result(tool_calls=[])
    report = CaseReport(case=case, result=result, evaluations=[])

    summary = summarize_trajectories(build_trajectory_reports([report]))
    assert summary["average_tool_precision"] is None


def test_compute_quality_metrics_reuses_pass_fail_and_healthy_rate():
    # One case passes everything and has a healthy trajectory; one case
    # fails an evaluator and has an unnecessary tool call.
    good_case = _case(id="good", expected_tools=[])
    good_result = _result(case_id="good", tool_calls=[])
    good_report = CaseReport(
        case=good_case,
        result=good_result,
        evaluations=[EvaluatorResult(evaluator="response_is_nonempty", outcome="pass")],
    )

    bad_case = _case(id="bad", expected_tools=[])
    bad_result = _result(case_id="bad", tool_calls=["search_hotels"])
    bad_report = CaseReport(
        case=bad_case,
        result=bad_result,
        evaluations=[EvaluatorResult(evaluator="tool_usage_matches_expected", outcome="fail")],
    )

    quality_pass_rate, trajectory_healthy_rate = compute_quality_metrics([good_report, bad_report])

    assert quality_pass_rate == 0.5  # 1 pass, 1 fail
    assert trajectory_healthy_rate == 0.5  # 1 healthy (no tool calls), 1 unhealthy (unnecessary)


def test_compute_quality_metrics_none_when_nothing_to_score():
    case = _case(expected_tools=[])
    result = _result(tool_calls=[])
    report = CaseReport(case=case, result=result, evaluations=[])

    quality_pass_rate, trajectory_healthy_rate = compute_quality_metrics([report])

    assert quality_pass_rate is None  # no pass/fail evaluations at all
    assert trajectory_healthy_rate == 1.0  # the one case has a healthy (empty) trajectory
