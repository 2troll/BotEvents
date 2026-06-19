"""Collector for public Wix Events pages (e.g. welcometokyoevents.com/osaka).

Wix sites embed their full events payload as JSON in a ``wix-warmup-data``
<script> tag, including title, start/end (UTC), venue, full address and
coordinates. We parse that structured JSON instead of scraping fragile HTML, so
events arrive already dated and geolocated (no Nominatim lookup needed).

Only public pages are read, and the target site's robots.txt is respected.
Configure one or more page URLs under ``sources.wixevents.pages``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

from ..config import Config
from ..models import Event
from .base import http_get, parse_datetime

log = logging.getLogger(__name__)

_WARMUP_RE = re.compile(
    r'id="wix-warmup-data"[^>]*>(.*?)</script>', re.DOTALL
)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("wixevents")
    pages: list[str] = sc.get("pages", []) or []
    events: list[Event] = []
    for url in pages:
        try:
            events.extend(_parse_page(url))
        except Exception as exc:  # noqa: BLE001 - isolate per-page failures
            log.warning("Wix events page failed %s: %s", url, exc)
    return events


def _parse_page(url: str) -> list[Event]:
    resp = http_get(url)
    if resp is None:
        return []
    match = _WARMUP_RE.search(resp.text)
    if not match:
        log.debug("No wix-warmup-data found on %s", url)
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        log.warning("Could not parse Wix warmup JSON on %s: %s", url, exc)
        return []

    raw_events = _find_events(data.get("appsWarmupData", data))
    if not raw_events:
        log.debug("No events list in Wix warmup data on %s", url)
        return []

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    events = [_to_event(item, base) for item in raw_events]
    return [e for e in events if e is not None]  # type: ignore[return-value]


def _find_events(node: Any) -> Optional[list[dict[str, Any]]]:
    """Recursively locate the Wix Events ``events`` list within the payload."""
    if isinstance(node, dict):
        candidate = node.get("events")
        if (
            isinstance(candidate, list)
            and candidate
            and isinstance(candidate[0], dict)
            and "title" in candidate[0]
        ):
            return candidate
        for value in node.values():
            found = _find_events(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_events(value)
            if found:
                return found
    return None


def _to_event(item: dict[str, Any], base: str) -> Optional[Event]:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    config = (item.get("scheduling") or {}).get("config", {})
    start = parse_datetime(config.get("startDate"))
    if start is None or config.get("scheduleTbd") or item.get("tbd"):
        return None  # skip undated / to-be-determined events

    location = item.get("location") or {}
    coords = location.get("coordinates") or {}
    lat = coords.get("lat")
    lng = coords.get("lng")

    page_url = item.get("siteEventPageUrl") or ""
    if page_url:
        full_url = base + page_url
    elif item.get("slug"):
        full_url = f"{base}/events/{item['slug']}"
    else:
        full_url = base

    return Event(
        title=title,
        start_dt=start,
        end_dt=parse_datetime(config.get("endDate")),
        venue=location.get("name") or "",
        address=location.get("fullAddress") or location.get("address") or "",
        lat=float(lat) if isinstance(lat, (int, float)) else None,
        lng=float(lng) if isinstance(lng, (int, float)) else None,
        tags=["wixevents", "international"],
        source="wixevents",
        url=full_url,
        description=(item.get("description") or "").strip(),
    )
