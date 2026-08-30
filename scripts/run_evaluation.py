#!/usr/bin/env python3
"""Milestone 9: run the deterministic evaluation suite.

Usage
-----
    make evaluate    # human-readable + machine-readable (JSON) report
    make eval-ci     # same, but exits 1 if any case crashed outright

`--ci` is NOT a baseline/regression gate — that's Milestone 17's explicit
job ("Establish a baseline... `make eval-ci` with configurable regression
thresholds", per the spec's Regression Testing section). Here it only fails
loudly on a broken pipeline (an exception raised while running a case),
which is a meaningfully different, and much simpler, signal than "did
quality regress."
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import (
    EVALUATORS,
    CaseReport,
    load_dataset,
    render_human_readable,
    run_case,
    summarize,
    to_machine_readable,
)
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider

RESULTS_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "results" / "latest.json"


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


async def _main(ci: bool) -> int:
    settings = get_settings()
    provider = get_llm_provider()

    reports, crashed = await _run_all()
    get_langfuse_client().flush()

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
    args = parser.parse_args()
    return asyncio.run(_main(ci=args.ci))


if __name__ == "__main__":
    raise SystemExit(main())
