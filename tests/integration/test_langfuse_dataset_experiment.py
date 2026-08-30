"""Integration test: real Langfuse dataset creation + run_experiment().

Excluded from `make test` (see `not integration` default in pyproject.toml).
Requires a live local Langfuse instance:

    make langfuse-up
    make test-integration

Uses a throwaway dataset (2 items, not the real 39-case
travel-concierge-eval-cases) with a scripted fake provider — same offline
"known behavior, not MockProvider's real limits" pattern established in
tests/unit/test_evaluation_runner.py (Milestone 9), so this test's
assertions don't depend on what MockProvider happens to do with the
message text.
"""

import uuid

import pytest

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation import run_named_experiment
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider
from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage

pytestmark = pytest.mark.integration


class _ScriptedHotelProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="The Algarve Beach Resort looks like a great match.",
                model=self.model,
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="search_hotels",
                    arguments={"destination_id": "algarve", "family_friendly": True},
                )
            ],
        )


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: _ScriptedHotelProvider()
    )
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_agent_graph.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_agent_graph.cache_clear()


def test_sync_and_run_experiment_end_to_end():
    # Dataset item ids must be unique per Langfuse *project*, not just per
    # dataset (confirmed the hard way: a fixed id here collided across two
    # runs of this exact test, in two different generated dataset names,
    # with a 409 from the real API — "item ids are unique per project
    # across datasets"). The same random suffix on both the dataset name
    # and every item id keeps repeated runs of this test collision-free.
    client = get_langfuse_client()
    suffix = uuid.uuid4().hex[:8]
    dataset_name = f"test-experiment-{suffix}"

    client.create_dataset(name=dataset_name)
    client.create_dataset_item(
        dataset_name=dataset_name,
        id=f"hotel-case-{suffix}",
        input={"message": "find me a hotel"},
        expected_output={"expected_tools": ["search_hotels"], "expected_arguments": {}},
        metadata={"case_id": "hotel-case", "query_class": "hotel_recommendation"},
    )
    client.create_dataset_item(
        dataset_name=dataset_name,
        id=f"chitchat-case-{suffix}",
        input={"message": "hello there"},
        expected_output={"expected_tools": []},
        metadata={"case_id": "chitchat-case", "query_class": "vague_request"},
    )

    result = run_named_experiment(run_name="integration-test-run", dataset_name=dataset_name)

    assert len(result.item_results) == 2
    assert result.dataset_run_id is not None
    assert result.dataset_run_url is not None

    by_case = {item.item.metadata["case_id"]: item for item in result.item_results}
    hotel_evaluations = {e.name: e.value for e in by_case["hotel-case"].evaluations}
    assert hotel_evaluations["tool_usage_matches_expected"] == 1.0
