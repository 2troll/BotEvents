"""Pluggable event sources.

Each collector is a callable ``(cfg) -> list[Event]`` that fetches public data
from one free source. :func:`collect_all` runs every enabled source with
per-source error isolation: one failing source never breaks the run.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..config import Config
from ..models import Event
from . import connpass, duckduckgo, html, ical, manual, rss, wixevents

log = logging.getLogger(__name__)

# name -> (enabled-check, collector)
_REGISTRY: dict[str, Callable[[Config], list[Event]]] = {
    "manual": manual.collect,
    "connpass": connpass.collect,
    "wixevents": wixevents.collect,
    "ical": ical.collect,
    "rss": rss.collect,
    "html": html.collect,
    "duckduckgo": duckduckgo.collect,
}


def collect_all(cfg: Config) -> list[Event]:
    """Collect events from all enabled sources with per-source isolation."""
    events: list[Event] = []
    for name, collector in _REGISTRY.items():
        if not cfg.source_enabled(name):
            log.debug("Source %s disabled; skipping", name)
            continue
        try:
            found = collector(cfg)
            log.info("Source %s returned %d events", name, len(found))
            events.extend(found)
        except Exception as exc:  # noqa: BLE001 - isolate any source failure
            log.exception("Source %s failed: %s", name, exc)
    log.info("Collected %d raw events from all sources", len(events))
    return events
