"""Telegram message formatting (HTML parse mode).

Pure functions: take events + config and return strings. No I/O here, so the
formatting is trivially testable and the same helpers feed both the autonomous
digest and the on-demand command replies.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from .config import Config
from .models import Event
from .scoring import category_emoji, why_matches


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def maps_url(event: Event) -> str:
    """Plain Google Maps link (a URL, not the paid API)."""
    if event.lat is not None and event.lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={event.lat},{event.lng}"
    query = event.location_query or event.title
    from urllib.parse import quote_plus

    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def fmt_price(price: str) -> str:
    if not price or price == "unknown":
        return "price TBA"
    if price == "free":
        return "Free"
    return price


def _when(event: Event, tz) -> str:
    if not event.start_dt:
        return "date TBA"
    dt = event.start_dt
    try:
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz)
    except (ValueError, OverflowError):
        pass
    return dt.strftime("%a %d %b, %H:%M")


def format_event_line(event: Event, cfg: Config, going: int = 0) -> str:
    """A single event block for the digest / replies."""
    emoji = category_emoji(event, cfg)
    title = _esc(event.title)
    if event.url:
        title = f'<a href="{_esc(event.url)}">{title}</a>'

    lines = [f"{emoji} <b>{title}</b>"]
    lines.append(f"🗓 {_esc(_when(event, cfg.tz))}")
    lines.append(f"✨ {_esc(why_matches(event, cfg))}")

    venue = event.venue or event.address
    if venue:
        lines.append(f'📍 {_esc(venue)} — <a href="{maps_url(event)}">Map</a>')
    lines.append(f"💴 {_esc(fmt_price(event.price))}")
    if event.major:
        lines.append("⭐ <i>major event</i>")
    if going:
        lines.append(f"🙋 {going} going")
    return "\n".join(lines)


def format_digest(
    events: list[Event],
    cfg: Config,
    going_counts: Optional[dict[str, int]] = None,
    map_url: str = "",
) -> str:
    """Morning digest grouped by day, newest section first."""
    going_counts = going_counts or {}
    header = "🛰 <b>Kansai Radar — today's picks</b>"
    if map_url:
        header += f'\n🗺 <a href="{_esc(map_url)}">Live event map</a>'

    if not events:
        return header + "\n\nNo matching events on the radar right now. 🌙"

    by_day: dict[str, list[Event]] = defaultdict(list)
    for event in sorted(events, key=_sort_key):
        day = event.start_dt.strftime("%A, %d %B %Y") if event.start_dt else "Date TBA"
        by_day[day].append(event)

    blocks = [header]
    for day, day_events in by_day.items():
        blocks.append(f"\n━━━ <b>{_esc(day)}</b> ━━━")
        for event in day_events:
            blocks.append(format_event_line(event, cfg, going_counts.get(event.id, 0)))
    return "\n\n".join(blocks)


def format_reminder(event: Event, cfg: Config, tier: str, going: int = 0) -> str:
    """Short standalone reminder message for one event."""
    titles = {
        "d30": "🗓 In about a month",
        "d7": "📌 One week to go",
        "d1": "⏰ Tomorrow",
        "day_before": "⏰ Tomorrow",
        "today": "📣 Today",
        "intraday": "🔥 Starting soon",
    }
    head = titles.get(tier, "🔔 Reminder")
    return f"{head}\n\n" + format_event_line(event, cfg, going)


def _sort_key(event: Event):
    return (event.start_dt is None, event.start_dt or datetime.max)
