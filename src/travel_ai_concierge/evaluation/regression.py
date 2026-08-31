"""Milestone 17: regression detection — compares the current evaluation run
against a committed baseline snapshot, gating `make eval-ci` on Milestone
14/16's own two-metric quality signal (`compute_quality_metrics`) rather
than either number alone. Milestone 16 demonstrated concretely why this
matters: a real regression there left the aggregate Layer 1 pass rate
moving in the *improving* direction while `trajectory_healthy_rate` caught
the actual damage — a gate watching only the first metric would have missed
exactly the bug this project actually shipped and had to diagnose by hand.

A baseline is a deliberate, reviewed snapshot (`data/evaluation/baseline.json`,
committed to git like `data/evaluation/cases.json`), written only by
`make eval-baseline` — never generated or silently overwritten by a normal
`make evaluate`/`make eval-ci` run. Establishing or updating it is a human
decision ("yes, this is the new normal"), the same reasoning this project
already applies to `make seed-prompts` (Milestone 8) never running
implicitly either.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["pass", "fail", "no_baseline"]


class Baseline(BaseModel):
    recorded_at: str
    llm_provider: str
    total_cases: int
    quality_pass_rate: float | None
    trajectory_healthy_rate: float


def build_baseline(
    *,
    llm_provider: str,
    total_cases: int,
    quality_pass_rate: float | None,
    trajectory_healthy_rate: float,
) -> Baseline:
    return Baseline(
        recorded_at=datetime.now(UTC).isoformat(),
        llm_provider=llm_provider,
        total_cases=total_cases,
        quality_pass_rate=quality_pass_rate,
        trajectory_healthy_rate=trajectory_healthy_rate,
    )


def load_baseline(path: Path) -> Baseline | None:
    if not path.exists():
        return None
    return Baseline.model_validate(json.loads(path.read_text()))


def save_baseline(path: Path, baseline: Baseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.model_dump(), indent=2) + "\n")


class MetricCheck(BaseModel):
    name: str
    baseline_value: float | None
    current_value: float | None
    delta: float | None  # current - baseline; negative means worse
    threshold: float  # max allowed drop, as a positive number
    regressed: bool


class RegressionCheckResult(BaseModel):
    verdict: Verdict
    baseline: Baseline | None
    checks: list[MetricCheck]


def check_regression(
    baseline: Baseline | None,
    *,
    quality_pass_rate: float | None,
    trajectory_healthy_rate: float,
    max_quality_drop: float,
    max_trajectory_drop: float,
) -> RegressionCheckResult:
    """Pure comparison logic — no I/O, no Settings access, so it's testable
    with hand-built fixtures the same way `evaluators.py`/`trajectory.py`
    already are. `baseline=None` (no baseline recorded yet) is `"no_baseline"`,
    not `"fail"` — you can't regress against nothing, and the spec's own
    milestone order ("establish a baseline" before "run evaluation") means
    a fresh checkout with no baseline yet must not fail CI.
    """
    if baseline is None:
        return RegressionCheckResult(verdict="no_baseline", baseline=None, checks=[])

    checks = [
        _check_metric(
            "quality_pass_rate", baseline.quality_pass_rate, quality_pass_rate, max_quality_drop
        ),
        _check_metric(
            "trajectory_healthy_rate",
            baseline.trajectory_healthy_rate,
            trajectory_healthy_rate,
            max_trajectory_drop,
        ),
    ]
    verdict: Verdict = "fail" if any(c.regressed for c in checks) else "pass"
    return RegressionCheckResult(verdict=verdict, baseline=baseline, checks=checks)


def _check_metric(
    name: str, baseline_value: float | None, current_value: float | None, threshold: float
) -> MetricCheck:
    if baseline_value is None or current_value is None:
        # Nothing to compare (e.g. every evaluation skipped on one side) —
        # same "skip isn't a failure" philosophy Layer 1 uses throughout.
        return MetricCheck(
            name=name,
            baseline_value=baseline_value,
            current_value=current_value,
            delta=None,
            threshold=threshold,
            regressed=False,
        )
    delta = current_value - baseline_value
    # A tiny epsilon guards against float noise landing a drop that's
    # conceptually *exactly* the threshold (e.g. 0.80 - 0.75) on the wrong
    # side of a strict `<` purely from binary floating-point rounding —
    # found by a test asserting the boundary itself, not a hypothetical.
    return MetricCheck(
        name=name,
        baseline_value=baseline_value,
        current_value=current_value,
        delta=delta,
        threshold=threshold,
        regressed=delta < -threshold - 1e-9,
    )


def render_regression_report(result: RegressionCheckResult) -> str:
    lines = ["Regression Check (Milestone 17)", "=" * 40]

    if result.verdict == "no_baseline":
        lines.append("No baseline recorded yet — run `make eval-baseline` to establish one.")
        lines.append("(Nothing to regress against, so this is not treated as a failure.)")
        return "\n".join(lines)

    baseline = result.baseline
    assert baseline is not None  # verdict != "no_baseline" guarantees this
    lines.append(
        f"Baseline: recorded {baseline.recorded_at}  "
        f"provider={baseline.llm_provider}  cases={baseline.total_cases}"
    )
    lines.append("")
    for check in result.checks:
        if check.delta is None:
            lines.append(
                f"  {check.name:<26} baseline={_fmt(check.baseline_value)}  "
                f"current={_fmt(check.current_value)}  (not comparable)"
            )
            continue
        marker = "REGRESSED" if check.regressed else "ok"
        lines.append(
            f"  {check.name:<26} baseline={_fmt(check.baseline_value)}  "
            f"current={_fmt(check.current_value)}  delta={check.delta:+.3f}  "
            f"max_drop={check.threshold:.3f}  [{marker}]"
        )
    lines.append("")
    lines.append(f"Verdict: {result.verdict.upper()}")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"
