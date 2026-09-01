#!/usr/bin/env python3
"""Milestone 21: the final experiment suite — a representative configuration
matrix, reported across every dimension the spec's own list names
(deterministic score, LLM judge score, human feedback where available, tool
accuracy, groundedness, latency, cost), closing with an auto-generated
final engineering analysis.

Usage
-----
    make final-experiment-suite

    # or directly, to edit CONFIGS below — a small, explicit list on
    # purpose, the same "not a generic experiment framework" choice
    # Milestone 14's own script already made:
    uv run python scripts/run_final_experiment_suite.py

The spec's own example matrix crosses prompt version against two different
*models* ("Model A"/"Model B") plus a tool-description variant. This
environment has no ANTHROPIC_API_KEY (the same recurring gap as every
real-provider comparison since Milestone 2), so a second real model can't
be exercised live here. The matrix below instead crosses the two axes that
actually are live and differentiable in this environment — PROMPT_LABEL
(Milestone 8) and AGENT_MAX_ITERATIONS (Milestone 14/17's own proven
differentiator) — while still exercising the exact same "prompt v1 vs v2"
axis the spec's example asks for. Swapping in a real second model is a
one-line change to CONFIGS's `env` dicts (add "LLM_PROVIDER": "anthropic",
"LLM_MODEL": "claude-...") the moment credentials exist — no script changes
needed, the same config-driven design Milestone 14 already established.

Every case still opens its own real Langfuse trace (unchanged `run_case()`),
tagged `final-experiment-suite` plus the specific config name.
"""

import asyncio
import json
import os
from pathlib import Path

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import (
    EVALUATORS,
    CaseJudgment,
    CaseReport,
    ConfigSuiteResult,
    final_suite_to_machine_readable,
    get_judge_provider,
    load_dataset,
    render_final_analysis,
    render_final_suite_report,
    run_case_with_metrics,
    run_config_suite,
)
from travel_ai_concierge.evaluation.judge import JudgeParseError
from travel_ai_concierge.observability import get_langfuse_client

RESULTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "evaluation"
    / "results"
    / "latest-final-suite.json"
)

CONFIGS = [
    {
        "name": "prod-v1 x multi-step",
        "env": {"PROMPT_LABEL": "production", "AGENT_MAX_ITERATIONS": "5"},
    },
    {
        "name": "staging-v2 x multi-step",
        "env": {"PROMPT_LABEL": "staging", "AGENT_MAX_ITERATIONS": "5"},
    },
    {
        "name": "prod-v1 x single-step",
        "env": {"PROMPT_LABEL": "production", "AGENT_MAX_ITERATIONS": "1"},
    },
    {
        "name": "staging-v2 x single-step",
        "env": {"PROMPT_LABEL": "staging", "AGENT_MAX_ITERATIONS": "1"},
    },
]


async def _run_config(name: str, env: dict[str, str]) -> ConfigSuiteResult:
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()

    judge = get_judge_provider()
    cases = load_dataset()
    reports: list[CaseReport] = []
    cost_latencies = []
    case_judgments: list[CaseJudgment] = []

    for case in cases:
        result, cost_latency = await run_case_with_metrics(
            case, config_name=name, experiment_tag="final-experiment-suite"
        )
        evaluations = [evaluator(case, result) for evaluator in EVALUATORS]
        reports.append(CaseReport(case=case, result=result, evaluations=evaluations))
        cost_latencies.append(cost_latency)

        try:
            judgments = await judge.judge(case, result)
        except JudgeParseError as exc:
            print(f"  judge parse failed for case {case.id!r}, retrying once ({exc})")
            try:
                judgments = await judge.judge(case, result)
            except JudgeParseError as exc2:
                print(f"  judge parse failed again for case {case.id!r}, skipping ({exc2})")
                continue
        case_judgments.append(
            CaseJudgment(case_id=case.id, query_class=case.query_class, judgments=judgments)
        )

    return run_config_suite(name, reports, cost_latencies, case_judgments, judge_model=judge.model)


async def _main() -> int:
    configs = []
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    for config in CONFIGS:
        print(f"Running config {config['name']!r}...")
        configs.append(await _run_config(config["name"], config["env"]))
        # Saved after every config, not just at the end — a config's LLM
        # calls are real, paid API usage, so a later config's failure
        # (e.g. a judge parse error surviving the retry above) must not
        # discard already-completed work.
        RESULTS_PATH.write_text(json.dumps(final_suite_to_machine_readable(configs), indent=2))

    get_langfuse_client().flush()

    print()
    print(render_final_suite_report(configs))
    print()
    print(render_final_analysis(configs))
    print(f"\nMachine-readable report: {RESULTS_PATH}")

    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
