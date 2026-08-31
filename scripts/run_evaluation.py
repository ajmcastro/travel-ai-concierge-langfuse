#!/usr/bin/env python3
"""Milestone 9: run the deterministic evaluation suite.

Usage
-----
    make evaluate         # human-readable + machine-readable (JSON) report
    make eval-baseline    # (re)record data/evaluation/baseline.json from this run (Milestone 17)
    make eval-ci          # exits 1 if any case crashed, OR a metric regressed past its threshold
    make evaluate-judged  # also score every case with the configured JudgeProvider (Milestone 11)

`--ci` checks two independent things (Milestone 17): (1) did any case crash
outright — a broken pipeline, and (2) did `quality_pass_rate` or
`trajectory_healthy_rate` drop by more than `Settings.regression_max_*_drop`
from the committed baseline. Both are printed on every run, `--ci` only
changes whether either turns into a non-zero exit code. With no baseline
recorded yet, the regression check reports `no_baseline` and never fails —
run `make eval-baseline` first.

`--with-judge` defaults to `Settings.judge_provider="fake"` (free, offline,
deterministic — see evaluation/judge.py). Set `JUDGE_PROVIDER=anthropic` for
a real judge — costs real latency/money across all 39 cases; read
evaluation/judge.py's module docstring for the documented limitations first.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import (
    EVALUATORS,
    CaseJudgment,
    CaseReport,
    build_baseline,
    build_trajectory_reports,
    check_regression,
    compute_quality_metrics,
    get_judge_provider,
    judge_to_machine_readable,
    load_baseline,
    load_dataset,
    render_human_readable,
    render_judge_summary,
    render_regression_report,
    render_trajectory_summary,
    run_case,
    save_baseline,
    summarize,
    summarize_judgments,
    summarize_trajectories,
    to_machine_readable,
    trajectory_to_machine_readable,
)
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider

RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "evaluation" / "results" / "latest.json"
)
JUDGE_RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "evaluation" / "results" / "latest-judged.json"
)
TRAJECTORY_RESULTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "evaluation"
    / "results"
    / "latest-trajectory.json"
)
BASELINE_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "baseline.json"


async def _run_all() -> tuple[list[CaseReport], int]:
    cases = load_dataset()
    reports: list[CaseReport] = []
    crashed = 0

    for case in cases:
        try:
            result = await run_case(case)
        except Exception as exc:  # noqa: BLE001 — a crashed case is itself a result to report, not fatal
            crashed += 1
            print(f"[{case.id}] CRASHED: {exc}", file=sys.stderr)
            continue

        evaluations = [evaluator(case, result) for evaluator in EVALUATORS]
        reports.append(CaseReport(case=case, result=result, evaluations=evaluations))

    return reports, crashed


async def _run_judge(reports: list[CaseReport]) -> list[CaseJudgment]:
    judge = get_judge_provider()
    case_judgments = []
    for report in reports:
        judgments = await judge.judge(report.case, report.result)
        case_judgments.append(
            CaseJudgment(
                case_id=report.case.id, query_class=report.case.query_class, judgments=judgments
            )
        )
    return case_judgments


async def _main(ci: bool, with_judge: bool, update_baseline: bool) -> int:
    settings = get_settings()
    provider = get_llm_provider()

    reports, crashed = await _run_all()

    summary = summarize(reports)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(to_machine_readable(reports, summary), indent=2))

    print(
        render_human_readable(
            reports,
            summary,
            provider_model=provider.model,
            prompt_label=settings.prompt_label,
            is_mock_provider=settings.llm_provider == "mock",
        )
    )
    print(f"\nMachine-readable report: {RESULTS_PATH}")

    # Milestone 13: always computed, unlike --with-judge — no LLM call, no
    # extra cost, purely derived from data _run_all() already collected.
    trajectory_reports = build_trajectory_reports(reports)
    trajectory_summary = summarize_trajectories(trajectory_reports)
    TRAJECTORY_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRAJECTORY_RESULTS_PATH.write_text(
        json.dumps(trajectory_to_machine_readable(trajectory_reports, trajectory_summary), indent=2)
    )
    print()
    print(render_trajectory_summary(trajectory_reports, trajectory_summary))
    print(f"\nMachine-readable trajectory report: {TRAJECTORY_RESULTS_PATH}")

    if with_judge:
        if settings.judge_provider != "fake":
            print(
                f"\nRunning judge_provider={settings.judge_provider!r} "
                f"(judge_model={settings.judge_model!r}) over {len(reports)} cases — "
                "real latency/cost, not the free default.",
                file=sys.stderr,
            )
        judge = get_judge_provider()
        case_judgments = await _run_judge(reports)
        judge_summary = summarize_judgments(case_judgments)

        JUDGE_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        JUDGE_RESULTS_PATH.write_text(
            json.dumps(judge_to_machine_readable(case_judgments, judge_summary), indent=2)
        )

        print()
        print(render_judge_summary(case_judgments, judge_summary, judge_model=judge.model))
        print(f"\nMachine-readable judge report: {JUDGE_RESULTS_PATH}")

    # Milestone 17: reuses the same (quality_pass_rate, trajectory_healthy_rate)
    # pair Milestone 14 established for cross-config comparison — see
    # trajectory_report.py's compute_quality_metrics() for why it's two
    # numbers, not one.
    quality_pass_rate, trajectory_healthy_rate = compute_quality_metrics(reports)

    exit_code = 0

    if update_baseline:
        baseline = build_baseline(
            llm_provider=settings.llm_provider,
            total_cases=len(reports),
            quality_pass_rate=quality_pass_rate,
            trajectory_healthy_rate=trajectory_healthy_rate,
        )
        save_baseline(BASELINE_PATH, baseline)
        print(f"\nBaseline recorded: {BASELINE_PATH}")
        print(
            f"  quality_pass_rate={quality_pass_rate}, "
            f"trajectory_healthy_rate={trajectory_healthy_rate}"
        )
    else:
        baseline = load_baseline(BASELINE_PATH)
        regression_result = check_regression(
            baseline,
            quality_pass_rate=quality_pass_rate,
            trajectory_healthy_rate=trajectory_healthy_rate,
            max_quality_drop=settings.regression_max_quality_drop,
            max_trajectory_drop=settings.regression_max_trajectory_drop,
        )
        print()
        print(render_regression_report(regression_result))
        if ci and regression_result.verdict == "fail":
            exit_code = 1

    get_langfuse_client().flush()

    if crashed:
        print(f"\n{crashed} case(s) crashed — see stderr above.", file=sys.stderr)
        if ci:
            exit_code = 1
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "exit non-zero if any case crashed, or if a metric regressed past its "
            "threshold vs. the committed baseline (Milestone 17)"
        ),
    )
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help="also score every case with the configured JudgeProvider (Settings.judge_provider, default 'fake')",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record this run's metrics as the new regression baseline (data/evaluation/baseline.json)",
    )
    args = parser.parse_args()
    return asyncio.run(
        _main(ci=args.ci, with_judge=args.with_judge, update_baseline=args.update_baseline)
    )


if __name__ == "__main__":
    raise SystemExit(main())
