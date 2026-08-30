#!/usr/bin/env python3
"""Milestone 10: publish/update data/evaluation/cases.json as a Langfuse Dataset.

Usage
-----
    make sync-eval-dataset

Safe to re-run after editing cases.json — dataset items are upserted by id
(each case's own `id`), not duplicated. Requires a reachable Langfuse
instance (`make langfuse-up`) — unlike prompts (Milestone 8), dataset
creation has no local fallback.
"""

from travel_ai_concierge.evaluation import DATASET_NAME, sync_dataset


def main() -> int:
    count = sync_dataset()
    print(f"Synced {count} cases to Langfuse dataset {DATASET_NAME!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
