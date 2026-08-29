import json
from functools import lru_cache
from pathlib import Path

from travel_ai_concierge.domain import Destination, Hotel

# data/synthetic/ lives at the repo root, not under src/ — resolved relative
# to this file rather than the process cwd, matching the pattern already
# used for locating ui/streamlit_app.py in tests/unit/test_ui_chat.py.
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "synthetic"


@lru_cache(maxsize=1)
def get_destinations() -> list[Destination]:
    raw = json.loads((DATA_DIR / "destinations.json").read_text())
    return [Destination.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def get_hotels() -> list[Hotel]:
    raw = json.loads((DATA_DIR / "hotels.json").read_text())
    return [Hotel.model_validate(item) for item in raw]
