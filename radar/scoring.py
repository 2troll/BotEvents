"""Local, keyword/rule-based relevance scoring.

No network and no LLM: an event's score is the summed weight of every interest
whose keywords appear in its searchable text. The highest-weighted matched
interest becomes the event's primary category (used for emoji + map colour).
"""

from __future__ import annotations

import logging
from typing import Any

from .config import Config
from .models import Event

log = logging.getLogger(__name__)


def _emoji_for(interests: list[dict[str, Any]], tag: str) -> str:
    for interest in interests:
        if interest.get("tag") == tag:
            return interest.get("emoji", "📌")
    return "📌"


def score_event(event: Event, cfg: Config) -> Event:
    """Annotate ``event`` in place with score, matched tags, category, major.

    Returns the same event for convenient chaining.
    """
    text = event.searchable_text
    interests = cfg.interests

    total = 0.0
    matched: list[str] = []
    best_tag = ""
    best_weight = -1.0

    for interest in interests:
        tag = interest.get("tag", "")
        weight = float(interest.get("weight", 1))
        keywords = [k.lower() for k in interest.get("keywords", [])]
        if any(kw and kw in text for kw in keywords):
            total += weight
            matched.append(tag)
            if weight > best_weight:
                best_weight = weight
                best_tag = tag

    event.score = round(total, 2)
    event.matched = matched
    event.category = best_tag
    event.major = _is_major(event, cfg)
    return event


def _is_major(event: Event, cfg: Config) -> bool:
    """A major event warrants advance (30/7/1-day) heads-up reminders."""
    if event.major:  # honour a manual flag carried from the source
        return True
    if event.category in cfg.major_categories:
        return True
    if event.attendee_count >= cfg.major_attendee_threshold:
        return True
    return False


def is_relevant(event: Event, cfg: Config) -> bool:
    """Whether to keep an event after scoring."""
    return event.score >= cfg.score_threshold


def why_matches(event: Event, cfg: Config) -> str:
    """A short, human one-liner explaining the match for the digest."""
    if not event.matched:
        return "matched your radar"
    labels = {
        i.get("tag"): f"{i.get('emoji', '')} {i.get('tag').replace('_', ' ')}".strip()
        for i in cfg.interests
    }
    names = [labels.get(tag, tag) for tag in event.matched[:3]]
    return "matches " + ", ".join(names)


def category_emoji(event: Event, cfg: Config) -> str:
    return _emoji_for(cfg.interests, event.category)
