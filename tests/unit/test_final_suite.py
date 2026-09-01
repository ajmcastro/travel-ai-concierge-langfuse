"""Tests for evaluation/final_suite.py — Milestone 21. Hand-built
CaseReport/CaseCostLatency/CaseJudgment fixtures, same discipline as
test_cost_latency_report.py/test_trajectory.py: this tests the composition
and rendering logic in isolation, not what a real 39-case run happens to
produce.
"""

from travel_ai_concierge.evaluation.cost_latency import CaseCostLatency
from travel_ai_concierge.evaluation.final_suite import (
    HUMAN_FEEDBACK_NOTE,
    ConfigSuiteResult,
    render_final_analysis,
    render_final_suite_report,
    run_config_suite,
    to_machine_readable,
)
from travel_ai_concierge.evaluation.judge import JudgmentResult
from travel_ai_concierge.evaluation.judge_report import CaseJudgment
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


def _judgment(**kwargs) -> JudgmentResult:
    defaults = {"dimension": "relevance", "score": 4, "rationale": "fine"}
    return JudgmentResult(**{**defaults, **kwargs})


def _case_judgment(**kwargs) -> CaseJudgment:
    defaults = {
        "case_id": "case-1",
        "query_class": "test",
        "judgments": [_judgment()],
    }
    return CaseJudgment(**{**defaults, **kwargs})


def _one_healthy_case_suite(config_name: str = "config-a") -> ConfigSuiteResult:
    case = _case(expected_tools=[])
    result = _result(tool_calls=[])
    report = CaseReport(
        case=case,
        result=result,
        evaluations=[
            EvaluatorResult(evaluator="response_is_nonempty", outcome="pass"),
            EvaluatorResult(evaluator="response_references_tool_result", outcome="skip"),
        ],
    )
    return run_config_suite(
        config_name,
        [report],
        [_cost_latency()],
        [_case_judgment()],
        judge_model="fake-judge-v1",
    )


# --- run_config_suite ---


def test_run_config_suite_reuses_compute_config_metrics_for_quality_and_cost():
    suite = _one_healthy_case_suite()
    assert suite.metrics.config_name == "config-a"
    assert suite.metrics.total_cases == 1
    assert suite.metrics.quality_pass_rate == 1.0  # one pass, no fails


def test_run_config_suite_computes_tool_precision_recall_from_trajectory():
    # No tools expected, none called -> vacuously healthy trajectory:
    # precision is None (nothing called), recall is 1.0 (nothing missed).
    suite = _one_healthy_case_suite()
    assert suite.average_tool_precision is None
    assert suite.average_tool_recall == 1.0


def test_run_config_suite_groundedness_proxy_isolates_that_one_evaluator():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"])
    report = CaseReport(
        case=case,
        result=result,
        evaluations=[
            EvaluatorResult(evaluator="response_is_nonempty", outcome="pass"),
            EvaluatorResult(evaluator="response_references_tool_result", outcome="fail"),
        ],
    )
    suite = run_config_suite(
        "config-a", [report], [_cost_latency()], [_case_judgment()], judge_model="fake-judge-v1"
    )
    assert suite.groundedness_proxy_pass_rate == 0.0


def test_run_config_suite_groundedness_proxy_is_none_when_no_case_has_it():
    # Only a skip for the groundedness evaluator -> nothing to compute a
    # rate from, same "None means not applicable" convention used elsewhere.
    suite = _one_healthy_case_suite()
    assert suite.groundedness_proxy_pass_rate is None


def test_run_config_suite_summarizes_judge_scores_per_dimension():
    judgments = [_case_judgment(judgments=[_judgment(dimension="relevance", score=5)])]
    suite = run_config_suite(
        "config-a",
        [CaseReport(case=_case(), result=_result(), evaluations=[])],
        [_cost_latency()],
        judgments,
        judge_model="fake-judge-v1",
    )
    assert suite.judge_summary["average_scores"]["relevance"] == 5.0
    assert suite.judge_model == "fake-judge-v1"


# --- to_machine_readable ---


def test_to_machine_readable_round_trips_config_names():
    suite = _one_healthy_case_suite("config-a")
    payload = to_machine_readable([suite])
    assert payload["configs"][0]["config_name"] == "config-a"


# --- render_final_suite_report ---


def test_render_final_suite_report_includes_every_required_dimension():
    suite = _one_healthy_case_suite()
    rendered = render_final_suite_report([suite])

    assert "deterministic score" in rendered
    assert "judge: relevance" in rendered
    assert "human feedback" in rendered
    assert HUMAN_FEEDBACK_NOTE in rendered
    assert "tool precision" in rendered
    assert "tool recall" in rendered
    assert "groundedness" in rendered
    assert "p50 latency" in rendered
    assert "avg estimated cost" in rendered


def test_render_final_suite_report_header_separates_long_config_names():
    # Same regression class Milestone 14 found for its own comparison table
    # (a fixed column width ran two long names together with no gap) —
    # pinned here too with deliberately long names.
    a = _one_healthy_case_suite("prod-v1 x multi-step (max_iter=5, default)")
    b = _one_healthy_case_suite("staging-v2 x single-step (max_iter=1)")
    rendered = render_final_suite_report([a, b])
    header = rendered.splitlines()[3]
    assert "step)staging" not in header
    assert "step)prod" not in header


def test_render_final_suite_report_handles_a_single_config_without_crashing():
    suite = _one_healthy_case_suite()
    rendered = render_final_suite_report([suite])
    assert "config-a" in rendered


# --- render_final_analysis ---


def test_render_final_analysis_recommends_the_higher_quality_config():
    good = _one_healthy_case_suite("good-config")

    bad_case = _case(expected_tools=["search_hotels"])
    bad_result = _result(tool_calls=[])
    bad_report = CaseReport(
        case=bad_case,
        result=bad_result,
        evaluations=[EvaluatorResult(evaluator="tool_usage_matches_expected", outcome="fail")],
    )
    bad = run_config_suite(
        "bad-config",
        [bad_report],
        [_cost_latency()],
        [_case_judgment()],
        judge_model="fake-judge-v1",
    )

    rendered = render_final_analysis([bad, good])

    assert "Recommended: 'good-config'" in rendered


def test_render_final_analysis_names_the_mock_invariance_caveat():
    suite = _one_healthy_case_suite()
    rendered = render_final_analysis([suite])
    assert "MockProvider" in rendered
    assert "AGENT_MAX_ITERATIONS" in rendered


def test_render_final_analysis_handles_no_configs():
    assert render_final_analysis([]) == "No configurations were run."
