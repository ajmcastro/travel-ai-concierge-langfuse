"""Milestone 14: aggregates cost_latency.py's per-case measurements into a
side-by-side comparison across two or more agent configurations, and
renders the spec's own requested discussion — "quality x latency x cost."

Quality is not invented here: it reuses Layer 1's own pass/fail rate
(evaluators.py, unchanged since Milestone 9) plus Milestone 13's trajectory
"healthy" rate as a second, more specific signal — the config axis this
milestone demonstrates (one LLM planning step vs two) is exactly the kind
of change trajectory health is built to notice (a single-step config can
never call a tool at all, which trajectory.py's `missing_tools` catches
directly), so reusing it here rather than inventing a third quality metric
is the same "reuse, don't duplicate" discipline established since M10.
"""

from typing import Any

from pydantic import BaseModel

from travel_ai_concierge.evaluation.cost_latency import CaseCostLatency
from travel_ai_concierge.evaluation.models import CaseReport
from travel_ai_concierge.evaluation.trajectory_report import build_trajectory_reports


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (numpy's default method) — no new
    dependency, small and fully deterministic for a handful of values.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class ConfigMetrics(BaseModel):
    config_name: str
    total_cases: int
    quality_pass_rate: float | None  # Layer 1: pass / (pass + fail), skips excluded
    trajectory_healthy_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    average_llm_calls: float
    total_input_tokens: int
    total_output_tokens: int
    average_input_tokens: float
    average_output_tokens: float
    total_estimated_cost_usd: float | None
    average_estimated_cost_usd: float | None


def compute_config_metrics(
    config_name: str, reports: list[CaseReport], cost_latencies: list[CaseCostLatency]
) -> ConfigMetrics:
    total_cases = len(reports)

    pass_count = sum(1 for r in reports for e in r.evaluations if e.outcome == "pass")
    fail_count = sum(1 for r in reports for e in r.evaluations if e.outcome == "fail")
    quality_pass_rate = (
        pass_count / (pass_count + fail_count) if (pass_count + fail_count) else None
    )

    trajectory_reports = build_trajectory_reports(reports)
    healthy_count = sum(1 for tr in trajectory_reports if tr.trajectory.is_healthy)
    trajectory_healthy_rate = healthy_count / total_cases if total_cases else 0.0

    latencies = [cl.total_latency_ms for cl in cost_latencies]
    llm_calls = [cl.llm_call_count for cl in cost_latencies]
    total_input = sum(cl.total_input_tokens for cl in cost_latencies)
    total_output = sum(cl.total_output_tokens for cl in cost_latencies)
    costs = [cl.estimated_cost_usd for cl in cost_latencies if cl.estimated_cost_usd is not None]

    return ConfigMetrics(
        config_name=config_name,
        total_cases=total_cases,
        quality_pass_rate=quality_pass_rate,
        trajectory_healthy_rate=trajectory_healthy_rate,
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        average_llm_calls=sum(llm_calls) / len(llm_calls) if llm_calls else 0.0,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        average_input_tokens=total_input / total_cases if total_cases else 0.0,
        average_output_tokens=total_output / total_cases if total_cases else 0.0,
        total_estimated_cost_usd=sum(costs) if costs else None,
        average_estimated_cost_usd=(sum(costs) / len(costs)) if costs else None,
    )


def to_machine_readable(configs: list[ConfigMetrics]) -> dict[str, Any]:
    return {"configs": [c.model_dump() for c in configs]}


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _fmt_cost(value: float | None) -> str:
    return f"${value:.4f}" if value is not None else "n/a"


def render_cost_latency_comparison(configs: list[ConfigMetrics]) -> str:
    lines = [
        "Cost and Latency Experiment (Milestone 14)",
        "=" * 40,
        "",
    ]

    # Width must accommodate the longest config name — a fixed width that's
    # merely "wide enough for typical names" silently ran two adjacent
    # columns together the first time this was run for real with
    # realistically long config names (see docs/EXPERIMENTS.md,
    # Milestone 14) — computed from actual content instead, plus a
    # guaranteed 2-space gap so this can't recur regardless of name length.
    col_width = max(22, max(len(c.config_name) for c in configs)) + 2

    header = f"{'metric':<28}" + "".join(f"{c.config_name:>{col_width}}" for c in configs)
    lines.append(header)
    lines.append("-" * len(header))

    def row(label: str, values: list[str]) -> str:
        return f"{label:<28}" + "".join(f"{v:>{col_width}}" for v in values)

    lines.append(row("cases", [str(c.total_cases) for c in configs]))
    lines.append(
        row("quality (Layer 1 pass rate)", [_fmt_pct(c.quality_pass_rate) for c in configs])
    )
    lines.append(
        row("trajectory healthy rate", [_fmt_pct(c.trajectory_healthy_rate) for c in configs])
    )
    lines.append(row("p50 latency (ms)", [f"{c.p50_latency_ms:.3f}" for c in configs]))
    lines.append(row("p95 latency (ms)", [f"{c.p95_latency_ms:.3f}" for c in configs]))
    lines.append(row("avg LLM calls / case", [f"{c.average_llm_calls:.2f}" for c in configs]))
    lines.append(row("avg input tokens / case", [f"{c.average_input_tokens:.1f}" for c in configs]))
    lines.append(
        row("avg output tokens / case", [f"{c.average_output_tokens:.1f}" for c in configs])
    )
    lines.append(
        row("avg estimated cost / case", [_fmt_cost(c.average_estimated_cost_usd) for c in configs])
    )

    lines.append("")
    lines.append(_discussion(configs))
    return "\n".join(lines)


def _discussion(configs: list[ConfigMetrics]) -> str:
    if len(configs) != 2:
        return (
            "Pareto discussion is only auto-generated for exactly two configs; "
            f"{len(configs)} were run — compare the table above by hand."
        )

    a, b = configs
    lines = ["Discussion (quality x latency x cost):"]

    if a.quality_pass_rate is not None and b.quality_pass_rate is not None:
        delta_pp = (b.quality_pass_rate - a.quality_pass_rate) * 100
        lines.append(
            f"  Quality: {b.config_name} is {delta_pp:+.1f} percentage points vs {a.config_name} "
            f"on Layer 1 pass rate, {(b.trajectory_healthy_rate - a.trajectory_healthy_rate) * 100:+.1f} "
            "points on trajectory health."
        )

    if a.p50_latency_ms and b.p50_latency_ms:
        ratio = b.p50_latency_ms / a.p50_latency_ms
        lines.append(f"  Latency: {b.config_name} p50 is {ratio:.2f}x {a.config_name}'s.")

    if a.average_output_tokens and b.average_output_tokens:
        ratio = (b.average_input_tokens + b.average_output_tokens) / (
            a.average_input_tokens + a.average_output_tokens
        )
        lines.append(
            f"  Tokens: {b.config_name} uses {ratio:.2f}x the tokens per case of {a.config_name}."
        )

    if a.average_estimated_cost_usd is not None and b.average_estimated_cost_usd is not None:
        cost_ratio = (
            b.average_estimated_cost_usd / a.average_estimated_cost_usd
            if a.average_estimated_cost_usd
            else None
        )
        lines.append(
            f"  Cost: {b.config_name} averages {_fmt_cost(b.average_estimated_cost_usd)}/case vs "
            f"{a.config_name}'s {_fmt_cost(a.average_estimated_cost_usd)}"
            + (f" ({cost_ratio:.2f}x)." if cost_ratio is not None else ".")
        )
    else:
        lines.append(
            "  Cost: n/a for at least one config (no priced model — see MODEL_PRICING in "
            "evaluation/cost_latency.py). MockProvider has no real inference cost; this axis "
            "only becomes meaningful with LLM_PROVIDER=anthropic."
        )

    return "\n".join(lines)
