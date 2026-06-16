"""RSS / Atom collector for public event and tourism feeds."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..models import Event

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("rss")
    feeds: list[str] = sc.get("feeds", []) or []
    if not feeds:
        return []
    try:
        import feedparser
    except ImportError:  # pragma: no cover
        log.warning("feedparser not installed; skipping RSS feeds")
        return []

    events: list[Event] = []
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                events.append(_to_event(entry, url))
        except Exception as exc:  # noqa: BLE001 - isolate per-feed failures
            log.warning("RSS feed failed %s: %s", url, exc)
    return events


def _to_event(entry: Any, source_url: str) -> Event:
    title = getattr(entry, "title", "").strip()
    summary = getattr(entry, "summary", "")
    # An RSS item's date is its *publish* date, not the event date, so we leave
    # start_dt empty and treat the item as a date-less "lead": it surfaces once
    # in the digest and then expires (see pipeline lead handling). Use iCal for
    # feeds that carry real structured event dates.
    return Event(
        title=title,
        start_dt=None,
        venue="",
        address="",
        tags=["rss", "lead"],
        source="rss",
        url=getattr(entry, "link", source_url),
        description=summary,
    )
