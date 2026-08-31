#!/usr/bin/env python3
"""Milestone 14: compare two agent configurations on quality, latency,
tokens, and estimated cost — the spec's own suggested "one LLM planning
step vs two" example.

Usage
-----
    make cost-latency-experiment

    # or directly, to add/change configs (edit CONFIGS below — this is a
    # small, explicit list on purpose, not a generic CLI flag system: the
    # milestone asks to compare "at least two" configurations, not to build
    # a general-purpose experiment framework):
    uv run python scripts/run_cost_latency_experiment.py

Runs the full 39-case dataset once per config, in the same process, via
env var overrides + `get_settings.cache_clear()` between configs (the same
technique test fixtures throughout this project already use to vary
Settings within one run). Each case still opens its own real Langfuse trace
(unchanged `run_case()`), so every trace is inspectable in Langfuse exactly
like any other evaluation run — this script's own report exists because
Langfuse's "events_only" mode (see docs/langfuse.md) has no read API to
pull a side-by-side comparison back from, not because the traces themselves
are hidden. Since this file's first version, every trace from this script
also carries a `cost-latency-experiment` tag plus the specific config name
(`single-step` / `multi-step (default)`, both in `langfuse.trace.tags` and
`metadata.cost_latency_config`) — filter Tracing by tag to browse them.

    # Also push each config as a named Langfuse Dataset Experiment run
    # (like `make experiment-prompt-v1`/`-v2` does for prompts, Milestone 10)
    # — gives a real dataset_run_url per config, comparable side by side
    # natively in Langfuse's own UI. Requires `make sync-eval-dataset` first
    # (the dataset must exist in Langfuse). Off by default: it re-runs the
    # full dataset a second time per config through unchanged M10 machinery
    # (no UsageTrackingProvider — this path only exists for native Langfuse
    # browsing, the local report above remains the authoritative numbers):
    uv run python scripts/run_cost_latency_experiment.py --push-to-langfuse
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import (
    EVALUATORS,
    CaseReport,
    ConfigMetrics,
    compute_config_metrics,
    cost_latency_to_machine_readable,
    load_dataset,
    render_cost_latency_comparison,
    run_case_with_metrics,
    run_named_experiment,
)
from travel_ai_concierge.observability import get_langfuse_client

RESULTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "evaluation"
    / "results"
    / "latest-cost-latency.json"
)

CONFIGS = [
    {"name": "single-step", "env": {"AGENT_MAX_ITERATIONS": "1"}},
    {"name": "multi-step (default)", "env": {"AGENT_MAX_ITERATIONS": "5"}},
]


async def _run_config(name: str, env: dict[str, str]) -> ConfigMetrics:
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()

    cases = load_dataset()
    reports = []
    cost_latencies = []
    for case in cases:
        result, cost_latency = await run_case_with_metrics(case, config_name=name)
        evaluations = [evaluator(case, result) for evaluator in EVALUATORS]
        reports.append(CaseReport(case=case, result=result, evaluations=evaluations))
        cost_latencies.append(cost_latency)

    return compute_config_metrics(name, reports, cost_latencies)


def _push_to_langfuse(name: str, env: dict[str, str]) -> str | None:
    """Pushes one config as a named Langfuse Dataset Experiment run, reusing
    M10's run_named_experiment() completely unchanged — no UsageTrackingProvider
    here, this path exists only so the config is browsable natively in
    Langfuse's own comparison UI, not to recompute local metrics a second way.
    Returns the dataset_run_url, or None if the dataset hasn't been synced.
    """
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()

    run_name = f"cost-latency-{name}".replace(" ", "-").replace("(", "").replace(")", "")
    try:
        result = run_named_experiment(
            run_name=run_name,
            description=f"Milestone 14: {name} agent configuration",
        )
    except Exception as exc:  # noqa: BLE001 — reported to the user, not fatal to the rest of the script
        print(
            f"  Could not push {name!r} to Langfuse: {exc}\n"
            "  (has `make sync-eval-dataset` been run? the dataset must exist in Langfuse first)"
        )
        return None
    return result.dataset_run_url


async def _main(push_to_langfuse: bool) -> int:
    configs = []
    for config in CONFIGS:
        print(f"Running config {config['name']!r}...")
        metrics = await _run_config(config["name"], config["env"])
        configs.append(metrics)

    get_langfuse_client().flush()

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(cost_latency_to_machine_readable(configs), indent=2))

    print()
    print(render_cost_latency_comparison(configs))
    print(f"\nMachine-readable report: {RESULTS_PATH}")

    if push_to_langfuse:
        print("\nPushing each config to Langfuse as a named Dataset Experiment run...")
        for config in CONFIGS:
            url = _push_to_langfuse(config["name"], config["env"])
            if url:
                print(f"  {config['name']}: {url}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--push-to-langfuse",
        action="store_true",
        help="also push each config as a named Langfuse Dataset Experiment run (requires `make sync-eval-dataset` first; re-runs the dataset a second time per config)",
    )
    args = parser.parse_args()
    return asyncio.run(_main(push_to_langfuse=args.push_to_langfuse))


if __name__ == "__main__":
    raise SystemExit(main())
