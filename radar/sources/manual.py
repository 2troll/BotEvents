"""Manual / hand-picked events defined directly in config.

A zero-network, 100%-reliable source: list well-known fixed-date events (big
festivals, fireworks, race days, anything you care about) in
``sources.manual.events`` and they always appear — no scraping, no key. Perfect
for famous annual Kansai events and for pinning your own plans to the map.

Each item supports: title, start, end, venue, address, lat, lng, tags, url,
price, attendee_count, major.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..models import Event
from .base import parse_datetime

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("manual")
    items: list[dict[str, Any]] = sc.get("events", []) or []
    events: list[Event] = []
    for item in items:
        try:
            event = _to_event(item)
            if event is not None:
                events.append(event)
        except Exception as exc:  # noqa: BLE001 - never let one bad entry break it
            log.warning("Manual event skipped (%s): %s", item.get("title"), exc)
    return events


def _to_event(item: dict[str, Any]) -> Event | None:
    title = item.get("title")
    if not title:
        return None
    lat = item.get("lat")
    lng = item.get("lng")
    tags = list(item.get("tags", []))
    if "manual" not in tags:
        tags.append("manual")
    return Event(
        title=title,
        start_dt=parse_datetime(item.get("start")),
        end_dt=parse_datetime(item.get("end")),
        venue=item.get("venue", ""),
        address=item.get("address", ""),
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
        tags=tags,
        price=item.get("price", "unknown"),
        source="manual",
        url=item.get("url", ""),
        description=item.get("description", ""),
        attendee_count=int(item.get("attendee_count", 0)),
        major=bool(item.get("major", False)),
    )
