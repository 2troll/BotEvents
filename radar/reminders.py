"""Reminder scheduling logic.

Decides which standalone reminders to fire on this run, given the current time
and each event's per-tier "already notified" flags. Pure decision logic: it
returns ``(event, tier)`` pairs and never sends anything itself, so it is fully
unit-testable and idempotent (a fired tier is recorded and never repeats).

Tiers:
  d30 / d7 / d1  — advance heads-up for MAJOR events (configurable days).
  day_before     — optional next-day mention for NORMAL events.
  intraday       — "starting soon" when an event begins within N hours.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .config import Config
from .models import Event

log = logging.getLogger(__name__)


def _localize(dt: Optional[datetime], tz) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def due_reminders(
    events: list[Event], cfg: Config, now: Optional[datetime] = None
) -> list[tuple[Event, str]]:
    """Return the reminders to fire now, in chronological-ish order."""
    tz = cfg.tz
    now = now.astimezone(tz) if now else datetime.now(tz)
    rc = cfg.get("reminders", default={}) or {}
    major_days = sorted(rc.get("major_days", [30, 7, 1]), reverse=True)
    normal_day_before = bool(rc.get("normal_day_before", True))
    intraday_hours = float(rc.get("intraday_hours", 3))

    due: list[tuple[Event, str]] = []
    for event in events:
        start = _localize(event.start_dt, tz)
        if start is None:
            continue
        delta = start - now
        hours_until = delta.total_seconds() / 3600.0
        days_until = (start.date() - now.date()).days

        if hours_until < -0.5:  # already started/over
            continue

        notified = event.notified

        # Intraday "starting soon" applies to every kept event.
        if 0 <= hours_until <= intraday_hours and not notified.get("intraday"):
            due.append((event, "intraday"))
            continue  # one reminder per run per event is plenty

        if event.major:
            for days in major_days:
                tier = f"d{days}"
                if days_until <= days and not notified.get(tier):
                    due.append((event, tier))
                    break
        elif (
            normal_day_before
            and days_until == 1
            and hours_until > intraday_hours  # not already imminent
            and not notified.get("day_before")
        ):
            due.append((event, "day_before"))

    log.info("%d reminder(s) due", len(due))
    return due
