"""Connpass collector — free JSON event API for tech/meetup events in Japan.

Connpass exposes a public JSON API. If an API key is configured via the
optional ``CONNPASS_API_KEY`` environment variable it is sent as a header, but
the collector is designed to work keyless and degrades gracefully (returns an
empty list) on any auth/rate error so it never breaks the run.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..config import Config
from ..models import Event
from .base import DEFAULT_HEADERS, parse_datetime
import requests

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("connpass")
    api_url: str = sc.get("api_url", "https://connpass.com/api/v2/events/")
    keywords: list[str] = sc.get("keywords", [])
    prefectures: list[str] = sc.get("prefectures", [])
    count: int = int(sc.get("count", 50))

    params: dict[str, Any] = {"count": count, "order": 2}  # order=2 -> by start date
    if keywords:
        params["keyword_or"] = ",".join(keywords)
    if prefectures:
        params["prefecture"] = ",".join(prefectures)

    headers = dict(DEFAULT_HEADERS)
    api_key = os.environ.get("CONNPASS_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        resp = requests.get(api_url, params=params, headers=headers, timeout=25)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Connpass fetch failed (continuing without it): %s", exc)
        return []

    raw_events = payload.get("events", []) or []
    events = [_to_event(item) for item in raw_events]
    return [e for e in events if e is not None]  # type: ignore[return-value]


def _to_event(item: dict[str, Any]) -> Event | None:
    title = item.get("title") or item.get("catch") or ""
    if not title:
        return None
    lat = item.get("lat")
    lng = item.get("lon")
    try:
        lat = float(lat) if lat not in (None, "") else None
        lng = float(lng) if lng not in (None, "") else None
    except (TypeError, ValueError):
        lat = lng = None

    accepted = item.get("accepted") or 0
    description = (item.get("catch") or "") + " " + (item.get("description") or "")
    return Event(
        title=title,
        start_dt=parse_datetime(item.get("started_at")),
        end_dt=parse_datetime(item.get("ended_at")),
        venue=item.get("place") or "",
        address=item.get("address") or "",
        lat=lat,
        lng=lng,
        tags=["connpass"],
        price="unknown",
        source="connpass",
        url=item.get("event_url") or item.get("url") or "",
        description=description.strip(),
        attendee_count=int(accepted) if str(accepted).isdigit() else 0,
    )
