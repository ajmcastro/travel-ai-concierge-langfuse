"""Tests for evaluation/cost_latency_report.py — Milestone 14. Hand-built
CaseReport/CaseCostLatency fixtures, same discipline as test_trajectory.py:
this tests the aggregation/rendering logic in isolation, not what any
provider happens to produce.
"""

from travel_ai_concierge.evaluation.cost_latency import CaseCostLatency
from travel_ai_concierge.evaluation.cost_latency_report import (
    _percentile,
    compute_config_metrics,
    render_cost_latency_comparison,
    to_machine_readable,
)
from travel_ai_concierge.evaluation.models import (
    CaseReport,
    CaseResult,
    EvaluationCase,
    EvaluatorResult,
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


def _cost_latency(**kwargs) -> CaseCostLatency:
    defaults = {
        "case_id": "case-1",
        "query_class": "test",
        "llm_call_count": 1,
        "total_latency_ms": 1.0,
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "estimated_cost_usd": None,
    }
    return CaseCostLatency(**{**defaults, **kwargs})


# --- _percentile ---


def test_percentile_of_empty_list_is_zero():
    assert _percentile([], 50) == 0.0


def test_percentile_of_single_value_is_that_value():
    assert _percentile([42.0], 95) == 42.0


def test_percentile_p50_of_a_known_sorted_list():
    # [1, 2, 3, 4, 5] -> p50 is the middle value, exactly
    assert _percentile([1, 2, 3, 4, 5], 50) == 3.0


def test_percentile_p0_and_p100_are_min_and_max():
    values = [5.0, 1.0, 3.0]
    assert _percentile(values, 0) == 1.0
    assert _percentile(values, 100) == 5.0


# --- compute_config_metrics ---


def test_compute_config_metrics_quality_pass_rate_excludes_skips():
    reports = [
        CaseReport(
            case=_case(),
            result=_result(),
            evaluations=[
                EvaluatorResult(evaluator="a", outcome="pass"),
                EvaluatorResult(evaluator="b", outcome="fail"),
                EvaluatorResult(evaluator="c", outcome="skip"),
            ],
        )
    ]
    metrics = compute_config_metrics("cfg", reports, [_cost_latency()])
    assert metrics.quality_pass_rate == 0.5  # 1 pass / (1 pass + 1 fail), skip excluded


def test_compute_config_metrics_quality_pass_rate_is_none_with_no_evaluations():
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    metrics = compute_config_metrics("cfg", reports, [_cost_latency()])
    assert metrics.quality_pass_rate is None


def test_compute_config_metrics_trajectory_healthy_rate():
    # One healthy (correct tool, no defects), one unhealthy (missing tool)
    healthy_case = _case(id="h", expected_tools=["search_hotels"])
    healthy_result = _result(case_id="h", tool_calls=["search_hotels"])
    unhealthy_case = _case(id="u", expected_tools=["search_hotels"])
    unhealthy_result = _result(case_id="u", tool_calls=[])

    reports = [
        CaseReport(case=healthy_case, result=healthy_result, evaluations=[]),
        CaseReport(case=unhealthy_case, result=unhealthy_result, evaluations=[]),
    ]
    cost_latencies = [_cost_latency(case_id="h"), _cost_latency(case_id="u")]

    metrics = compute_config_metrics("cfg", reports, cost_latencies)
    assert metrics.trajectory_healthy_rate == 0.5


def test_compute_config_metrics_latency_percentiles_and_token_averages():
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    cost_latencies = [
        _cost_latency(total_latency_ms=10.0, total_input_tokens=100, total_output_tokens=50),
        _cost_latency(total_latency_ms=20.0, total_input_tokens=200, total_output_tokens=100),
    ]
    # total_cases below is deliberately just 1 report but 2 cost_latencies —
    # exercised separately from quality since a real caller always passes
    # matching-length lists; this only checks the latency/token math itself.
    metrics = compute_config_metrics("cfg", reports, cost_latencies)

    assert metrics.p50_latency_ms == 15.0
    assert metrics.total_input_tokens == 300
    assert metrics.total_output_tokens == 150


def test_compute_config_metrics_cost_is_none_when_no_case_has_a_priced_model():
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    metrics = compute_config_metrics("cfg", reports, [_cost_latency(estimated_cost_usd=None)])
    assert metrics.total_estimated_cost_usd is None
    assert metrics.average_estimated_cost_usd is None


def test_compute_config_metrics_cost_averages_only_priced_cases():
    reports = [
        CaseReport(case=_case(), result=_result(), evaluations=[]),
        CaseReport(case=_case(), result=_result(), evaluations=[]),
    ]
    cost_latencies = [
        _cost_latency(estimated_cost_usd=0.01),
        _cost_latency(estimated_cost_usd=0.03),
    ]
    metrics = compute_config_metrics("cfg", reports, cost_latencies)
    assert metrics.total_estimated_cost_usd == 0.04
    assert metrics.average_estimated_cost_usd == 0.02


# --- render / to_machine_readable: smoke tests ---


def test_render_comparison_includes_both_config_names_and_a_discussion():
    reports_a = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    reports_b = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    a = compute_config_metrics("config-a", reports_a, [_cost_latency(total_latency_ms=5.0)])
    b = compute_config_metrics("config-b", reports_b, [_cost_latency(total_latency_ms=10.0)])

    rendered = render_cost_latency_comparison([a, b])

    assert "config-a" in rendered
    assert "config-b" in rendered
    assert "Discussion" in rendered


def test_render_comparison_header_separates_long_config_names():
    # Regression guard: the first real run used config names longer than the
    # column's originally-fixed width, and two adjacent columns ran together
    # with no separating whitespace at all (see docs/EXPERIMENTS.md,
    # Milestone 14). Column width must scale with the actual name length.
    long_name_a = "single-step-with-a-long-descriptive-name"
    long_name_b = "multi-step-with-an-even-longer-descriptive-name"
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    a = compute_config_metrics(long_name_a, reports, [_cost_latency()])
    b = compute_config_metrics(long_name_b, reports, [_cost_latency()])

    rendered = render_cost_latency_comparison([a, b])
    header_line = next(line for line in rendered.splitlines() if long_name_a in line)

    assert f"{long_name_a}{long_name_b}" not in header_line.replace("  ", " ")
    assert long_name_a in header_line.split()
    assert long_name_b in header_line.split()


def test_render_comparison_handles_a_single_config_without_crashing():
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    only = compute_config_metrics("only-config", reports, [_cost_latency()])
    rendered = render_cost_latency_comparison([only])
    assert "only-config" in rendered
    assert "only were run" in rendered or "1 were run" in rendered


def test_to_machine_readable_round_trips_config_names():
    reports = [CaseReport(case=_case(), result=_result(), evaluations=[])]
    metrics = compute_config_metrics("cfg", reports, [_cost_latency()])
    data = to_machine_readable([metrics])
    assert data["configs"][0]["config_name"] == "cfg"
