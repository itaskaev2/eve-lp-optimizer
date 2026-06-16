"""Thin client for CCP's public ESI API.

Only public, unauthenticated endpoints are used:
  * GET  /loyalty/stores/{corporation_id}/offers/  -> LP store offers
  * POST /universe/ids/                            -> name  -> id resolution
  * POST /universe/names/                          -> id    -> name resolution

See https://esi.evetech.net/ for the full API documentation.
"""

from __future__ import annotations

import time
from typing import Iterable

import requests

ESI_BASE = "https://esi.evetech.net/latest"
DEFAULT_USER_AGENT = (
    "eve-lp-optimizer/1.0 (+https://github.com/itaskaev2/eve-lp-optimizer)"
)


class EsiError(RuntimeError):
    """Raised when ESI returns an unrecoverable error."""


class EsiClient:
    def __init__(
        self,
        base_url: str = ESI_BASE,
        user_agent: str = DEFAULT_USER_AGENT,
        datasource: str = "tranquility",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.datasource = datasource
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )

    # -- low level ---------------------------------------------------------
    def _request(self, method: str, path: str, *, params=None, json=None,
                 max_retries: int = 4) -> requests.Response:
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        params.setdefault("datasource", self.datasource)
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = self.session.request(
                    method, url, params=params, json=json, timeout=self.timeout
                )
            except requests.RequestException as exc:  # network hiccup
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            # Transient server / gateway errors -> retry.
            if resp.status_code in (502, 503, 504, 520):
                time.sleep(1.5 * (attempt + 1))
                continue
            # ESI error-rate limiter -> back off hard.
            if resp.status_code == 420:
                time.sleep(10)
                continue
            if not resp.ok:
                raise EsiError(
                    f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return resp
        raise EsiError(f"{method} {path} failed after {max_retries} attempts: {last_exc}")

    def _get_paged(self, path: str, params=None) -> list:
        """Collect every page of a paginated GET endpoint (X-Pages header)."""
        results: list = []
        page = 1
        while True:
            p = dict(params or {})
            p["page"] = page
            resp = self._request("GET", path, params=p)
            data = resp.json()
            if not data:
                break
            results.extend(data)
            try:
                pages = int(resp.headers.get("X-Pages", "1"))
            except ValueError:
                pages = 1
            if page >= pages:
                break
            page += 1
        return results

    # -- public endpoints --------------------------------------------------
    def loyalty_offers(self, corporation_id: int) -> list[dict]:
        """Return all LP store offers for an NPC corporation."""
        return self._get_paged(f"/loyalty/stores/{int(corporation_id)}/offers/")

    def resolve_names(self, names: Iterable[str]) -> dict:
        """POST /universe/ids/ — resolve names to ids across categories."""
        resp = self._request("POST", "/universe/ids/", json=list(names))
        return resp.json()

    def names_for_ids(self, ids: Iterable[int]) -> dict[int, str]:
        """POST /universe/names/ — resolve ids to names (batched, max 1000)."""
        unique = [int(i) for i in dict.fromkeys(int(x) for x in ids)]
        out: dict[int, str] = {}
        for start in range(0, len(unique), 1000):
            chunk = unique[start:start + 1000]
            resp = self._request("POST", "/universe/names/", json=chunk)
            for entry in resp.json():
                out[int(entry["id"])] = entry["name"]
        return out

    def resolve_corporation(self, name_or_id: str | int) -> tuple[int, str]:
        """Resolve a corporation by numeric id or by (case-insensitive) name."""
        text = str(name_or_id).strip()
        if text.isdigit():
            cid = int(text)
            names = self.names_for_ids([cid])
            return cid, names.get(cid, text)

        data = self.resolve_names([text])
        corps = data.get("corporations") or []
        if not corps:
            raise EsiError(f"No corporation found matching {name_or_id!r}")
        for corp in corps:  # prefer an exact (case-insensitive) match
            if corp["name"].lower() == text.lower():
                return int(corp["id"]), corp["name"]
        return int(corps[0]["id"]), corps[0]["name"]
