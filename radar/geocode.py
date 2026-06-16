"""Free geocoding via OpenStreetMap Nominatim with aggressive local caching.

Compliance with the Nominatim usage policy:
- A descriptive User-Agent is always sent.
- At most one request every ``min_interval_sec`` seconds (default >1s).
- Results are cached in ``state.json`` forever, so each unique location string
  is looked up at most once across the project's lifetime.
- A per-run cap bounds total requests so a run never hammers the service.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import Config
from .models import Event
from .state import State

log = logging.getLogger(__name__)


class Geocoder:
    """Rate-limited, cached Nominatim geocoder."""

    def __init__(self, cfg: Config, state: State) -> None:
        gc = cfg.get("geocode", default={}) or {}
        self.enabled: bool = bool(gc.get("enabled", True))
        self.url: str = gc.get("nominatim_url", "https://nominatim.openstreetmap.org/search")
        self.user_agent: str = gc.get("user_agent", "KansaiRadar/1.0")
        self.min_interval: float = float(gc.get("min_interval_sec", 1.2))
        self.max_lookups: int = int(gc.get("max_lookups_per_run", 25))
        self.country_hint: str = cfg.get("region", "country_hint", default="Japan")
        self.cache = state.geocode_cache
        self._last_request = 0.0
        self._lookups = 0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def geocode(self, query: str) -> Optional[tuple[float, float]]:
        """Return (lat, lng) for ``query`` using the cache when possible."""
        if not query:
            return None
        key = query.strip().lower()
        if key in self.cache:
            cached = self.cache[key]
            return (cached[0], cached[1]) if cached else None

        if not self.enabled:
            return None
        if self._lookups >= self.max_lookups:
            log.debug("Geocode lookup cap (%d) reached; skipping %r", self.max_lookups, query)
            return None

        coords = self._request(query)
        # Cache both hits and misses (None) to avoid repeat lookups.
        self.cache[key] = list(coords) if coords else None
        self._lookups += 1
        return coords

    def _request(self, query: str) -> Optional[tuple[float, float]]:
        params = {
            "q": f"{query}, {self.country_hint}",
            "format": "json",
            "limit": 1,
        }
        try:
            self._throttle()
            resp = requests.get(
                self.url,
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
                log.debug("Geocoded %r -> (%.4f, %.4f)", query, lat, lng)
                return (lat, lng)
            log.debug("No geocode result for %r", query)
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            log.warning("Geocode failed for %r: %s", query, exc)
        return None

    def enrich(self, event: Event) -> Event:
        """Fill an event's lat/lng from its location query when missing."""
        if event.lat is not None and event.lng is not None:
            return event
        coords = self.geocode(event.location_query)
        if coords:
            event.lat, event.lng = coords
        return event
