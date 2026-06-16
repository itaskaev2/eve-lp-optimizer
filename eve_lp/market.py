"""Jita market prices via the Fuzzwork aggregates API.

Fuzzwork pre-calculates buy/sell aggregates per station, which is far cheaper
than paging raw ESI market orders for hundreds of types. Endpoint:

    https://market.fuzzwork.co.uk/aggregates/?station=<id>&types=<csv>

Each type returns ``buy`` and ``sell`` objects with weightedAverage / max / min
/ median / percentile / volume / orderCount (all as strings).
"""

from __future__ import annotations

from typing import Iterable

import requests

FUZZWORK_AGGREGATES = "https://market.fuzzwork.co.uk/aggregates/"

# Jita IV - Moon 4 - Caldari Navy Assembly Plant (the main trade hub).
JITA_STATION_ID = 60003760

_PRICE_FIELDS = (
    "weightedAverage", "max", "min", "median", "percentile", "volume", "orderCount",
)


class MarketError(RuntimeError):
    """Raised when the market data provider cannot be reached."""


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_aggregate(payload: dict) -> dict:
    parsed = {}
    for side in ("buy", "sell"):
        side_data = payload.get(side, {}) or {}
        parsed[side] = {field: _to_float(side_data.get(field)) for field in _PRICE_FIELDS}
    return parsed


class JitaMarket:
    def __init__(
        self,
        station_id: int = JITA_STATION_ID,
        user_agent: str = "eve-lp-optimizer/1.0",
        timeout: int = 30,
        batch_size: int = 100,
    ) -> None:
        self.station_id = station_id
        self.timeout = timeout
        self.batch_size = batch_size
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )

    def prices(self, type_ids: Iterable[int]) -> dict[int, dict]:
        """Return ``{type_id: {"buy": {...}, "sell": {...}}}`` for the station."""
        unique = [int(t) for t in dict.fromkeys(int(x) for x in type_ids)]
        out: dict[int, dict] = {}
        for start in range(0, len(unique), self.batch_size):
            chunk = unique[start:start + self.batch_size]
            params = {"station": self.station_id, "types": ",".join(map(str, chunk))}
            try:
                resp = self.session.get(
                    FUZZWORK_AGGREGATES, params=params, timeout=self.timeout
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise MarketError(f"Fuzzwork request failed: {exc}") from exc
            for tid, payload in resp.json().items():
                out[int(tid)] = _parse_aggregate(payload)
        return out
