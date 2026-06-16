"""Local, keyword/rule-based relevance scoring.

No network and no LLM: an event's score is the summed weight of every interest
whose keywords appear in its searchable text. The highest-weighted matched
interest becomes the event's primary category (used for emoji + map colour).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Union

from .config import Config
from .models import Event

log = logging.getLogger(__name__)

# A matcher is either a compiled regex (word-boundary, for Latin keywords) or a
# plain lowercase string (substring containment, for CJK keywords which have no
# word boundaries). Built once per config and cached on the Config instance.
Matcher = Union[re.Pattern, str]


def _compile_keyword(keyword: str) -> Matcher | None:
    """Build a matcher for one keyword.

    Latin/ASCII keywords use word-boundary matching so short tokens like "IT"
    or "tour" never match inside unrelated words ("kitchen", "tourist's stuff").
    CJK keywords (Japanese) fall back to substring containment.
    """
    kw = keyword.strip().lower()
    if not kw:
        return None
    if kw.isascii():
        # \b is unreliable around non-word chars; use explicit lookarounds.
        return re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])")
    return kw


def _matchers(cfg: Config) -> list[dict[str, Any]]:
    """Return (and cache) the compiled interest matchers for this config."""
    cached = getattr(cfg, "_score_matchers", None)
    if cached is not None:
        return cached
    built: list[dict[str, Any]] = []
    for interest in cfg.interests:
        matchers = [_compile_keyword(k) for k in interest.get("keywords", [])]
        built.append(
            {
                "tag": interest.get("tag", ""),
                "weight": float(interest.get("weight", 1)),
                "matchers": [m for m in matchers if m is not None],
            }
        )
    cfg._score_matchers = built  # type: ignore[attr-defined]
    return built


def _hit(matcher: Matcher, text: str) -> bool:
    if isinstance(matcher, str):
        return matcher in text
    return matcher.search(text) is not None


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

    total = 0.0
    matched: list[str] = []
    best_tag = ""
    best_weight = -1.0

    for interest in _matchers(cfg):
        if any(_hit(m, text) for m in interest["matchers"]):
            weight = interest["weight"]
            total += weight
            matched.append(interest["tag"])
            if weight > best_weight:
                best_weight = weight
                best_tag = interest["tag"]

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
