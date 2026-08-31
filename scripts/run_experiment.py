#!/usr/bin/env python3
"""Milestone 10: run the synced Langfuse dataset as a named experiment.

Usage
-----
    make sync-eval-dataset       # once, or after editing cases.json
    make experiment-prompt-v1    # PROMPT_LABEL=production, run_name="prompt-v1"
    make experiment-prompt-v2    # PROMPT_LABEL=staging,   run_name="prompt-v2"

    # or directly, to name your own comparison axis:
    uv run python scripts/run_experiment.py --run-name my-run --description "..."

    # Milestone 11: also push LLM-as-judge scores (judge_relevance, etc.) as
    # additional Evaluations on the same dataset run:
    uv run python scripts/run_experiment.py --run-name my-run --with-judge

Milestone 13: every run also pushes trajectory_* Evaluations (tool_precision,
tool_recall, agent_steps, healthy) unconditionally, no flag needed — unlike
--with-judge, trajectory metrics cost nothing extra (no LLM call, purely
derived from data the task already collects). See
travel_ai_concierge.evaluation.experiment._trajectory_evaluator.

Each run is linked to the same Langfuse dataset under a different run_name —
open the printed dataset_run_url to compare runs side by side in Langfuse's
own UI (quality scores, cost, tokens, latency per generation — all native to
Langfuse already, not recomputed here; see docs/RATIONALE_PER_MILESTONE.md,
Milestone 10, for why).
"""

import argparse

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import run_named_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-name", required=True, help="distinguishes this run from others on the same dataset"
    )
    parser.add_argument("--description", default=None)
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help="also push LLM-as-judge scores (Settings.judge_provider, default 'fake') as additional Evaluations",
    )
    args = parser.parse_args()

    if args.with_judge and get_settings().judge_provider != "fake":
        print(
            "Running a real judge over every dataset item — real latency/cost, not the free default."
        )

    result = run_named_experiment(
        run_name=args.run_name, description=args.description, with_judge=args.with_judge
    )
    print(result.format())
    if result.dataset_run_url:
        print(f"\nCompare this run against others in Langfuse: {result.dataset_run_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
