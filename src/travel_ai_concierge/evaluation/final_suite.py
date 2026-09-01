"""Milestone 21: the final experiment suite — a representative configuration
matrix, reported across every dimension the spec's own list names
(deterministic score, LLM judge score, human feedback where available, tool
accuracy, groundedness, latency, cost), closing with an auto-generated
"which configuration should we deploy, and why" analysis.

Nothing here is a new measurement mechanism. Every number reused below was
built in an earlier milestone: `compute_config_metrics()` (M14/M17) for
quality/trajectory/latency/cost, `summarize_trajectories()` (M13) for tool
precision/recall, Layer 1's `response_references_tool_result` evaluator (M9)
for the groundedness proxy, `summarize_judgments()` (M11) for the LLM judge.
This module's only real job is composing them into one report per config
and one N-config comparison, instead of a fourth, fifth, and sixth
re-implementation of "average this list of numbers."

"Human feedback where available" is reported as a fixed, explanatory note,
not a number — `POST /feedback` (M12) scores real, live `/chat` traffic;
this suite runs the offline 39-case dataset, which no human has ever rated.
Reporting a fabricated feedback score would be worse than reporting none.
"""

from typing import Any

from pydantic import BaseModel

from travel_ai_concierge.evaluation.cost_latency import CaseCostLatency
from travel_ai_concierge.evaluation.cost_latency_report import ConfigMetrics, compute_config_metrics
from travel_ai_concierge.evaluation.judge_report import CaseJudgment, summarize_judgments
from travel_ai_concierge.evaluation.models import CaseReport
from travel_ai_concierge.evaluation.trajectory_report import (
    build_trajectory_reports,
    summarize_trajectories,
)

HUMAN_FEEDBACK_NOTE = (
    "n/a for this offline suite — POST /feedback (Milestone 12) scores real, "
    "live /chat traffic; no human has rated any of these 39 synthetic cases."
)


def _groundedness_proxy_pass_rate(reports: list[CaseReport]) -> float | None:
    """Layer 1's `response_references_tool_result` pass rate, isolated from
    the other four evaluators — the same "pass / (pass + fail), skips
    excluded" convention `compute_quality_metrics()` (M17) already uses for
    the all-evaluator aggregate, applied here to one evaluator specifically.
    """
    outcomes = [
        e.outcome
        for r in reports
        for e in r.evaluations
        if e.evaluator == "response_references_tool_result"
    ]
    passed = outcomes.count("pass")
    failed = outcomes.count("fail")
    return passed / (passed + failed) if (passed + failed) else None


class ConfigSuiteResult(BaseModel):
    config_name: str
    metrics: ConfigMetrics
    average_tool_precision: float | None
    average_tool_recall: float | None
    groundedness_proxy_pass_rate: float | None
    judge_model: str
    judge_summary: dict[str, Any]


def run_config_suite(
    config_name: str,
    reports: list[CaseReport],
    cost_latencies: list[CaseCostLatency],
    case_judgments: list[CaseJudgment],
    *,
    judge_model: str,
) -> ConfigSuiteResult:
    """Pure aggregation — no I/O, no agent run. Takes what a real run
    already collected and composes it into one report-ready object, the
    same "pure logic, separate from the async runner" split `compute_config_metrics()`
    and `check_regression()` already use, specifically so this is testable
    with hand-built fixtures instead of needing a real 39-case run per test.
    """
    trajectory_summary = summarize_trajectories(build_trajectory_reports(reports))
    return ConfigSuiteResult(
        config_name=config_name,
        metrics=compute_config_metrics(config_name, reports, cost_latencies),
        average_tool_precision=trajectory_summary["average_tool_precision"],
        average_tool_recall=trajectory_summary["average_tool_recall"],
        groundedness_proxy_pass_rate=_groundedness_proxy_pass_rate(reports),
        judge_model=judge_model,
        judge_summary=summarize_judgments(case_judgments),
    )


def to_machine_readable(configs: list[ConfigSuiteResult]) -> dict[str, Any]:
    return {"configs": [c.model_dump() for c in configs]}


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def _fmt_cost(value: float | None) -> str:
    return f"${value:.4f}" if value is not None else "n/a"


def _fmt_score(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def render_final_suite_report(configs: list[ConfigSuiteResult]) -> str:
    lines = [
        "Final Experiment Suite (Milestone 21)",
        "=" * 40,
        "",
    ]

    # Same column-width-from-content discipline Milestone 14's own
    # comparison table had to add after a real run silently ran two
    # adjacent columns together with a fixed width (see docs/EXPERIMENTS.md,
    # Milestone 14) — never hardcode this again.
    col_width = max(22, max(len(c.config_name) for c in configs)) + 2

    header = f"{'metric':<32}" + "".join(f"{c.config_name:>{col_width}}" for c in configs)
    lines.append(header)
    lines.append("-" * len(header))

    def row(label: str, values: list[str]) -> str:
        return f"{label:<32}" + "".join(f"{v:>{col_width}}" for v in values)

    lines.append(
        row(
            "deterministic score (Layer 1)",
            [_fmt_pct(c.metrics.quality_pass_rate) for c in configs],
        )
    )
    judge_dimensions = sorted(
        {dim for c in configs for dim in c.judge_summary.get("average_scores", {})}
    )
    for dim in judge_dimensions:
        lines.append(
            row(
                f"judge: {dim}",
                [_fmt_score(c.judge_summary["average_scores"].get(dim)) for c in configs],
            )
        )
    lines.append(row("human feedback", ["n/a" for _ in configs]))
    lines.append(row("tool precision", [_fmt_pct(c.average_tool_precision) for c in configs]))
    lines.append(row("tool recall", [_fmt_pct(c.average_tool_recall) for c in configs]))
    lines.append(
        row("groundedness (proxy)", [_fmt_pct(c.groundedness_proxy_pass_rate) for c in configs])
    )
    lines.append(
        row(
            "trajectory healthy rate",
            [_fmt_pct(c.metrics.trajectory_healthy_rate) for c in configs],
        )
    )
    lines.append(row("p50 latency (ms)", [f"{c.metrics.p50_latency_ms:.3f}" for c in configs]))
    lines.append(row("p95 latency (ms)", [f"{c.metrics.p95_latency_ms:.3f}" for c in configs]))
    lines.append(
        row(
            "avg estimated cost / case",
            [_fmt_cost(c.metrics.average_estimated_cost_usd) for c in configs],
        )
    )

    lines.append("")
    lines.append(f"Human feedback: {HUMAN_FEEDBACK_NOTE}")
    lines.append(
        f"Judge model: {configs[0].judge_model if configs else 'n/a'} — see "
        "docs/architecture.md's 'LLM-as-Judge' section for documented biases and limitations."
    )

    return "\n".join(lines)


def render_final_analysis(configs: list[ConfigSuiteResult]) -> str:
    """The spec's own closing question, answered directly: "Which
    configuration should we deploy, and why?" Ranks by the same two-metric
    philosophy Milestone 17's regression gate already established
    (quality_pass_rate, trajectory_healthy_rate) rather than inventing a
    third ranking scheme, then reports the latency/cost cost of the winner.
    """
    if not configs:
        return "No configurations were run."

    lines = ["Final Engineering Analysis", "=" * 40, ""]

    ranked = sorted(
        configs,
        key=lambda c: (
            c.metrics.quality_pass_rate if c.metrics.quality_pass_rate is not None else -1,
            c.metrics.trajectory_healthy_rate,
        ),
        reverse=True,
    )
    winner = ranked[0]

    lines.append(
        f"Recommended: {winner.config_name!r} — highest deterministic quality "
        f"({_fmt_pct(winner.metrics.quality_pass_rate)}) and trajectory health "
        f"({_fmt_pct(winner.metrics.trajectory_healthy_rate)}) among the {len(configs)} "
        "configurations compared."
    )
    lines.append(
        f"  Cost of that choice: p50 latency {winner.metrics.p50_latency_ms:.3f}ms, "
        f"~{winner.metrics.average_input_tokens + winner.metrics.average_output_tokens:.0f} "
        f"tokens/case, estimated cost {_fmt_cost(winner.metrics.average_estimated_cost_usd)}/case."
    )

    if len(ranked) > 1:
        runner_up = ranked[1]
        if runner_up.metrics.p50_latency_ms and winner.metrics.p50_latency_ms:
            ratio = winner.metrics.p50_latency_ms / runner_up.metrics.p50_latency_ms
            lines.append(
                f"  Runner-up {runner_up.config_name!r}: {_fmt_pct(runner_up.metrics.quality_pass_rate)} "
                f"quality at {ratio:.2f}x the winner's p50 latency."
            )

    lines.append("")
    lines.append(
        "Caveat (verified, not assumed): under the default MockProvider, prompt "
        "content and tool-call descriptions are never read by the model's own "
        "decision logic (see providers/llm/mock.py) — any configs differing only "
        "by PROMPT_LABEL are expected, structurally, to score identically here. "
        "This suite's real, live-differentiating axis in this environment is "
        "AGENT_MAX_ITERATIONS (Milestone 14/17's own finding, reused, not "
        "rediscovered). A real prompt-quality or model comparison needs "
        "LLM_PROVIDER=anthropic — not exercised live in this environment, no "
        "ANTHROPIC_API_KEY configured, the same recurring gap as every other "
        "real-provider comparison in this project."
    )

    return "\n".join(lines)
