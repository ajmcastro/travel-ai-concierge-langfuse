import json
from functools import lru_cache
from pathlib import Path

from travel_ai_concierge.evaluation.models import EvaluationCase

# Path resolved via module location, not cwd — same pattern as
# providers/travel_search/data.py's get_destinations()/get_hotels().
_DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "evaluation" / "cases.json"


@lru_cache(maxsize=1)
def load_dataset() -> list[EvaluationCase]:
    raw = json.loads(_DATASET_PATH.read_text())
    return [EvaluationCase.model_validate(item) for item in raw]
