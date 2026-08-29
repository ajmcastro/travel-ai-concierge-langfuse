from typing import Literal

from pydantic import BaseModel

PriceBand = Literal["budget", "mid", "luxury"]

_PRICE_BAND_ORDER: dict[PriceBand, int] = {"budget": 0, "mid": 1, "luxury": 2}


class Destination(BaseModel):
    id: str
    name: str
    country: str
    region: str
    climate: str
    tags: list[str]
    best_months: list[str]
    description: str


class Hotel(BaseModel):
    id: str
    destination_id: str
    name: str
    star_rating: int
    customer_rating: float
    price_band: PriceBand
    family_friendly: bool
    adults_only: bool
    amenities: list[str]


def price_band_at_most(band: PriceBand, maximum: PriceBand) -> bool:
    return _PRICE_BAND_ORDER[band] <= _PRICE_BAND_ORDER[maximum]
