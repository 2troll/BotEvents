"""RSS / Atom collector for public event and tourism feeds."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..models import Event
from .base import parse_datetime

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
    # Published/updated date acts as the event start when no better data exists.
    when = (
        getattr(entry, "published", None)
        or getattr(entry, "updated", None)
        or getattr(entry, "start", None)
    )
    summary = getattr(entry, "summary", "")
    return Event(
        title=title,
        start_dt=parse_datetime(when),
        venue="",
        address="",
        tags=["rss"],
        source="rss",
        url=getattr(entry, "link", source_url),
        description=summary,
    )
