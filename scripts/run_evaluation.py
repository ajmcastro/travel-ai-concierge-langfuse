#!/usr/bin/env python3
"""Milestone 9: run the deterministic evaluation suite.

Usage
-----
    make evaluate         # human-readable + machine-readable (JSON) report
    make eval-ci          # same, but exits 1 if any case crashed outright
    make evaluate-judged  # also score every case with the configured JudgeProvider (Milestone 11)

`--ci` is NOT a baseline/regression gate — that's Milestone 17's explicit
job ("Establish a baseline... `make eval-ci` with configurable regression
thresholds", per the spec's Regression Testing section). Here it only fails
loudly on a broken pipeline (an exception raised while running a case),
which is a meaningfully different, and much simpler, signal than "did
quality regress."

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
    build_trajectory_reports,
    get_judge_provider,
    judge_to_machine_readable,
    load_dataset,
    render_human_readable,
    render_judge_summary,
    render_trajectory_summary,
    run_case,
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


async def _main(ci: bool, with_judge: bool) -> int:
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

    get_langfuse_client().flush()

    if crashed:
        print(f"\n{crashed} case(s) crashed — see stderr above.", file=sys.stderr)
        if ci:
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci",
        action="store_true",
        help="exit non-zero if any case crashed (not a regression/baseline gate — see Milestone 17)",
    )
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help="also score every case with the configured JudgeProvider (Settings.judge_provider, default 'fake')",
    )
    args = parser.parse_args()
    return asyncio.run(_main(ci=args.ci, with_judge=args.with_judge))


if __name__ == "__main__":
    raise SystemExit(main())
