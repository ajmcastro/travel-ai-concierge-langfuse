import json
from functools import lru_cache
from pathlib import Path

from travel_ai_concierge.domain import Destination, Hotel

# data/synthetic/ lives at the repo root, not under src/ — resolved relative
# to this file rather than the process cwd, matching the pattern already
# used for locating ui/streamlit_app.py in tests/unit/test_ui_chat.py.
# Milestone 18: this module moved from tools/data.py to
# providers/travel_search/data.py (one directory deeper — parents[4], not
# parents[3] — to break an import cycle: tools/__init__.py eagerly imports
# travel_tools.py, which imports providers.travel_search, which (before the
# move) needed tools.data, forcing tools/__init__.py to still be mid-import
# when travel_tools.py tried to import providers.travel_search back again).
DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "synthetic"


@lru_cache(maxsize=1)
def get_destinations() -> list[Destination]:
    raw = json.loads((DATA_DIR / "destinations.json").read_text())
    return [Destination.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def get_hotels() -> list[Hotel]:
    raw = json.loads((DATA_DIR / "hotels.json").read_text())
    return [Hotel.model_validate(item) for item in raw]
