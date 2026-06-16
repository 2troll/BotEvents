"""iCal (.ics) collector for public event/tourism calendars."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from ..config import Config
from ..models import Event
from .base import http_get

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("ical")
    feeds: list[str] = sc.get("feeds", []) or []
    events: list[Event] = []
    for url in feeds:
        try:
            events.extend(_parse_feed(url))
        except Exception as exc:  # noqa: BLE001 - isolate per-feed failures
            log.warning("iCal feed failed %s: %s", url, exc)
    return events


def _parse_feed(url: str) -> list[Event]:
    resp = http_get(url)
    if resp is None:
        return []
    try:
        from icalendar import Calendar
    except ImportError:  # pragma: no cover
        log.warning("icalendar not installed; skipping iCal feeds")
        return []

    cal = Calendar.from_ical(resp.content)
    events: list[Event] = []
    for component in cal.walk("VEVENT"):
        events.append(_to_event(component, url))
    return events


def _to_event(component: Any, source_url: str) -> Event:
    title = str(component.get("summary", "")).strip()
    start = _coerce(component.get("dtstart"))
    end = _coerce(component.get("dtend"))
    location = str(component.get("location", "")).strip()
    description = str(component.get("description", "")).strip()
    url = str(component.get("url", "")) or source_url
    return Event(
        title=title,
        start_dt=start,
        end_dt=end,
        venue=location,
        address=location,
        tags=["ical"],
        source="ical",
        url=url,
        description=description,
    )


def _coerce(field: Any) -> datetime | None:
    """Convert an icalendar date/datetime field to a datetime."""
    if field is None:
        return None
    value = getattr(field, "dt", field)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None
