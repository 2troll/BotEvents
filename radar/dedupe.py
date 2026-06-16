"""Cross-source de-duplication of normalized events.

Two events are considered the same real-world event when they share a fuzzy
title key and start on the same day. The richer record (more fields populated)
wins, but we keep the higher attendee_count and any coordinates.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from .models import Event

log = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^0-9a-z぀-ヿ一-鿿]+")


def _title_key(title: str) -> str:
    """Normalize a title for fuzzy comparison (keeps JP kana/kanji)."""
    key = _NON_ALNUM.sub("", title.lower())
    return key[:40]


def _dedupe_key(event: Event) -> str:
    day = event.start_dt.date().isoformat() if event.start_dt else "nodate"
    return f"{_title_key(event.title)}|{day}"


def _richness(event: Event) -> int:
    """How complete an event record is (used to pick the survivor)."""
    fields = [event.venue, event.address, event.url, event.description]
    score = sum(1 for f in fields if f)
    if event.lat is not None:
        score += 1
    return score


def dedupe(events: Iterable[Event]) -> list[Event]:
    """Collapse duplicates, merging useful fields into the survivor."""
    best: dict[str, Event] = {}
    for event in events:
        key = _dedupe_key(event)
        if key not in best:
            best[key] = event
            continue
        incumbent = best[key]
        winner, loser = (
            (event, incumbent)
            if _richness(event) > _richness(incumbent)
            else (incumbent, event)
        )
        # Merge: prefer winner, backfill from loser.
        winner.attendee_count = max(winner.attendee_count, loser.attendee_count)
        if winner.lat is None and loser.lat is not None:
            winner.lat, winner.lng = loser.lat, loser.lng
        if not winner.url:
            winner.url = loser.url
        if not winner.description:
            winner.description = loser.description
        if not winner.venue:
            winner.venue = loser.venue
        best[key] = winner

    result = list(best.values())
    log.info("Deduped to %d unique events", len(result))
    return result
