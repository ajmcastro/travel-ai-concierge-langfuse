"""Milestone 10: publish/update the local evaluation dataset as a real
Langfuse Dataset.

"The local JSON/JSONL dataset should remain version-controlled and
reproducible. Langfuse is an execution/analysis layer, not the only source
of truth for test cases" (project spec) — `data/evaluation/cases.json`
stays the source of truth; this only mirrors it into Langfuse so
`run_experiment()` (experiment.py) has something to iterate and link
traces/scores against.
"""

from travel_ai_concierge.evaluation.dataset import load_dataset
from travel_ai_concierge.observability import get_langfuse_client

DATASET_NAME = "travel-concierge-eval-cases"


def sync_dataset() -> int:
    """Create/update the Langfuse Dataset from data/evaluation/cases.json.

    Idempotent: `create_dataset_item(id=...)` upserts by id rather than
    duplicating (verified against the SDK's own docstring — "Upserts if an
    item with id already exists") — using each case's own `id` as the
    Langfuse item id means re-running this after editing cases.json updates
    existing items in place instead of accumulating duplicates.
    """
    client = get_langfuse_client()
    cases = load_dataset()

    client.create_dataset(
        name=DATASET_NAME,
        description="Milestone 9's local deterministic evaluation dataset, synced (Milestone 10).",
    )
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=case.id,
            input={"message": case.message},
            expected_output={
                "expected_tools": case.expected_tools,
                "expected_arguments": case.expected_arguments,
                "expects_clarification": case.expects_clarification,
            },
            metadata={"case_id": case.id, "query_class": case.query_class},
        )

    client.flush()
    return len(cases)
