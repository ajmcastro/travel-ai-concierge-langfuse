#!/usr/bin/env python3
"""Milestone 10: run the synced Langfuse dataset as a named experiment.

Usage
-----
    make sync-eval-dataset       # once, or after editing cases.json
    make experiment-prompt-v1    # PROMPT_LABEL=production, run_name="prompt-v1"
    make experiment-prompt-v2    # PROMPT_LABEL=staging,   run_name="prompt-v2"

    # or directly, to name your own comparison axis:
    uv run python scripts/run_experiment.py --run-name my-run --description "..."

Each run is linked to the same Langfuse dataset under a different run_name —
open the printed dataset_run_url to compare runs side by side in Langfuse's
own UI (quality scores, cost, tokens, latency per generation — all native to
Langfuse already, not recomputed here; see docs/RATIONALE_PER_MILESTONE.md,
Milestone 10, for why).
"""

import argparse

from travel_ai_concierge.evaluation import run_named_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True, help="distinguishes this run from others on the same dataset")
    parser.add_argument("--description", default=None)
    args = parser.parse_args()

    result = run_named_experiment(run_name=args.run_name, description=args.description)
    print(result.format())
    if result.dataset_run_url:
        print(f"\nCompare this run against others in Langfuse: {result.dataset_run_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
