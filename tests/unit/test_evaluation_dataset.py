"""Tests for the Milestone 9 evaluation dataset itself.

Offline: just reads data/evaluation/cases.json off disk, no agent/provider
invocation — that's tested separately in test_evaluation_runner.py.
"""

from travel_ai_concierge.evaluation.dataset import load_dataset

# The spec's own list of query classes the dataset "should include" — a
# concrete, checkable coverage requirement, not just an aspiration.
REQUIRED_QUERY_CLASSES = {
    "destination_recommendation",
    "hotel_recommendation",
    "family_holiday",
    "couples_holiday",
    "budget",
    "luxury",
    "beach",
    "city",
    "culture",
    "nightlife",
    "quiet",
    "food_wine",
    "itinerary_planning",
    "vague_request",
    "multi_constraint",
    "requires_clarification",
    "requires_one_tool",
    "requires_multiple_tools",
    "impossible_constraint",
    "contradictory_preferences",
}


def test_dataset_size_is_within_spec_range():
    cases = load_dataset()
    assert 30 <= len(cases) <= 50


def test_case_ids_are_unique():
    cases = load_dataset()
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_every_required_query_class_is_covered():
    cases = load_dataset()
    covered = {c.query_class for c in cases}
    missing = REQUIRED_QUERY_CLASSES - covered
    assert not missing, f"missing query classes: {missing}"


def test_every_case_expects_a_tool_or_clarification_or_neither_explicitly():
    # Not every case needs a tool (impossible-constraint-001 expects none),
    # but every case should have made a deliberate choice — this just
    # confirms the schema round-trips cleanly with no case silently
    # defaulting to something unintended.
    cases = load_dataset()
    for case in cases:
        assert isinstance(case.expected_tools, list)
        assert isinstance(case.expects_clarification, bool)


def test_expected_arguments_only_reference_the_first_expected_tool_scope():
    # Sanity check on the dataset's own convention (see EvaluationCase's
    # docstring): expected_arguments is only ever meaningful when there's at
    # least one expected tool to check it against.
    cases = load_dataset()
    for case in cases:
        if case.expected_arguments:
            assert case.expected_tools, f"{case.id} has expected_arguments but no expected_tools"


def test_dataset_is_cached():
    assert load_dataset() is load_dataset()
