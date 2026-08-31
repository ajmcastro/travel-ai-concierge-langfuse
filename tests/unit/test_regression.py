"""Tests for evaluation/regression.py — Milestone 17. Pure comparison logic
tested with hand-built Baseline fixtures, same discipline as
test_trajectory.py/test_evaluators.py: no agent run, no I/O beyond the two
small file-roundtrip tests.
"""

from travel_ai_concierge.evaluation.regression import (
    Baseline,
    build_baseline,
    check_regression,
    load_baseline,
    render_regression_report,
    save_baseline,
)


def _baseline(**kwargs) -> Baseline:
    defaults = {
        "recorded_at": "2026-08-31T00:00:00+00:00",
        "llm_provider": "mock",
        "total_cases": 39,
        "quality_pass_rate": 0.80,
        "trajectory_healthy_rate": 0.60,
    }
    return Baseline(**{**defaults, **kwargs})


def test_no_baseline_is_not_a_failure():
    result = check_regression(
        None,
        quality_pass_rate=0.10,
        trajectory_healthy_rate=0.10,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    assert result.verdict == "no_baseline"
    assert result.checks == []


def test_metrics_within_threshold_pass():
    result = check_regression(
        _baseline(quality_pass_rate=0.80, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.78,  # -0.02, within 0.05
        trajectory_healthy_rate=0.61,  # improved
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    assert result.verdict == "pass"
    assert all(not c.regressed for c in result.checks)


def test_quality_drop_past_threshold_fails():
    result = check_regression(
        _baseline(quality_pass_rate=0.80, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.70,  # -0.10, past 0.05
        trajectory_healthy_rate=0.60,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    assert result.verdict == "fail"
    quality_check = next(c for c in result.checks if c.name == "quality_pass_rate")
    assert quality_check.regressed is True
    assert round(quality_check.delta, 3) == -0.1
    trajectory_check = next(c for c in result.checks if c.name == "trajectory_healthy_rate")
    assert trajectory_check.regressed is False


def test_trajectory_drop_past_threshold_fails_even_when_quality_improves():
    """The Milestone 16 shape, exactly: aggregate quality goes UP while
    trajectory health goes down — the gate must still catch it via the
    second metric.
    """
    result = check_regression(
        _baseline(quality_pass_rate=0.80, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.85,  # improved
        trajectory_healthy_rate=0.40,  # -0.20, past 0.05
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    assert result.verdict == "fail"
    quality_check = next(c for c in result.checks if c.name == "quality_pass_rate")
    assert quality_check.regressed is False
    trajectory_check = next(c for c in result.checks if c.name == "trajectory_healthy_rate")
    assert trajectory_check.regressed is True


def test_drop_exactly_at_threshold_does_not_regress():
    """Boundary: a drop of exactly the threshold is not "past" it — the
    check is a strict `<`, matching how the threshold is described ("max
    allowed drop").
    """
    result = check_regression(
        _baseline(quality_pass_rate=0.80, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.75,  # exactly -0.05
        trajectory_healthy_rate=0.60,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    assert result.verdict == "pass"


def test_none_quality_pass_rate_is_not_comparable_not_a_failure():
    """If a whole run has nothing to score (all evaluations skipped), that's
    "not comparable," not treated as a regression — same as evaluators.py's
    own skip philosophy.
    """
    result = check_regression(
        _baseline(quality_pass_rate=None, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.90,
        trajectory_healthy_rate=0.60,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    quality_check = next(c for c in result.checks if c.name == "quality_pass_rate")
    assert quality_check.delta is None
    assert quality_check.regressed is False
    assert result.verdict == "pass"


def test_render_no_baseline_report():
    result = check_regression(
        None,
        quality_pass_rate=0.5,
        trajectory_healthy_rate=0.5,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    rendered = render_regression_report(result)

    assert "No baseline recorded yet" in rendered
    assert "make eval-baseline" in rendered


def test_render_fail_report_names_the_regressed_metric():
    result = check_regression(
        _baseline(quality_pass_rate=0.80, trajectory_healthy_rate=0.60),
        quality_pass_rate=0.60,
        trajectory_healthy_rate=0.60,
        max_quality_drop=0.05,
        max_trajectory_drop=0.05,
    )

    rendered = render_regression_report(result)

    assert "Verdict: FAIL" in rendered
    assert "quality_pass_rate" in rendered
    assert "REGRESSED" in rendered


def test_build_baseline_captures_given_metrics():
    baseline = build_baseline(
        llm_provider="mock",
        total_cases=39,
        quality_pass_rate=0.87,
        trajectory_healthy_rate=0.5,
    )

    assert baseline.llm_provider == "mock"
    assert baseline.total_cases == 39
    assert baseline.quality_pass_rate == 0.87
    assert baseline.trajectory_healthy_rate == 0.5
    assert baseline.recorded_at  # non-empty ISO timestamp


def test_save_and_load_baseline_roundtrip(tmp_path):
    path = tmp_path / "baseline.json"
    baseline = _baseline()

    save_baseline(path, baseline)
    loaded = load_baseline(path)

    assert loaded == baseline


def test_load_baseline_returns_none_when_missing(tmp_path):
    assert load_baseline(tmp_path / "does-not-exist.json") is None
