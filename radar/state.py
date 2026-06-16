"""Persistent state stored in a single JSON file committed back to the repo.

The state holds:
- ``events``: every known upcoming event keyed by id (with per-tier notified
  flags), so reminders are never repeated.
- ``geocode_cache``: location string -> [lat, lng], so Nominatim is queried
  at most once per unique location, ever.
- ``going``: event id -> list of user identifiers who marked /voy.
- ``telegram_offset``: getUpdates offset so each command is processed once.
- ``last_digest_date`` / ``last_run_utc``: idempotency bookkeeping.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .models import Event

log = logging.getLogger(__name__)

_DEFAULT: dict[str, Any] = {
    "version": 1,
    "events": {},
    "geocode_cache": {},
    "going": {},
    "telegram_offset": 0,
    "last_digest_date": None,
    "last_run_utc": None,
}


class State:
    """In-memory view of ``state.json`` with typed helpers and atomic save."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self._path = path

    # -- loading / saving ---------------------------------------------------

    @classmethod
    def load(cls, path: str | Path = "state.json") -> "State":
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not read state %s (%s); starting fresh", p, exc)
                data = {}
        else:
            data = {}
        merged = {**_DEFAULT, **data}
        for key, value in _DEFAULT.items():
            merged.setdefault(key, value)
        return cls(merged, p)

    def save(self) -> None:
        """Atomically write state to disk (write-temp-then-replace)."""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self._path)
        log.debug("Saved state to %s (%d events)", self._path, len(self.events_raw))

    # -- events -------------------------------------------------------------

    @property
    def events_raw(self) -> dict[str, dict[str, Any]]:
        return self._data["events"]

    def all_events(self) -> list[Event]:
        return [Event.from_dict(d) for d in self.events_raw.values()]

    def get_event(self, event_id: str) -> Optional[Event]:
        raw = self.events_raw.get(event_id)
        return Event.from_dict(raw) if raw else None

    def upsert_event(self, event: Event) -> Event:
        """Insert a new event or merge into the existing one, preserving the
        notified flags and any prior enrichment (e.g. cached coordinates)."""
        existing = self.events_raw.get(event.id)
        if existing:
            event.notified = {**existing.get("notified", {}), **event.notified}
            # Preserve the original first-seen timestamp across updates.
            if existing.get("first_seen") and not event.first_seen:
                event.first_seen = existing["first_seen"]
            # Keep coordinates if the new copy lacks them.
            if event.lat is None and existing.get("lat") is not None:
                event.lat = existing["lat"]
                event.lng = existing["lng"]
        self.events_raw[event.id] = event.to_dict()
        return event

    def remove_event(self, event_id: str) -> None:
        self.events_raw.pop(event_id, None)

    # -- geocode cache ------------------------------------------------------

    @property
    def geocode_cache(self) -> dict[str, Any]:
        return self._data["geocode_cache"]

    # -- going / interactivity ---------------------------------------------

    @property
    def going(self) -> dict[str, list[str]]:
        return self._data["going"]

    def mark_going(self, event_id: str, who: str) -> int:
        attendees = self._data["going"].setdefault(event_id, [])
        if who not in attendees:
            attendees.append(who)
        return len(attendees)

    def going_count(self, event_id: str) -> int:
        return len(self._data["going"].get(event_id, []))

    # -- telegram bookkeeping ----------------------------------------------

    @property
    def telegram_offset(self) -> int:
        return int(self._data.get("telegram_offset", 0))

    @telegram_offset.setter
    def telegram_offset(self, value: int) -> None:
        self._data["telegram_offset"] = int(value)

    @property
    def last_digest_date(self) -> Optional[str]:
        return self._data.get("last_digest_date")

    @last_digest_date.setter
    def last_digest_date(self, value: Optional[str]) -> None:
        self._data["last_digest_date"] = value

    @property
    def last_run_utc(self) -> Optional[str]:
        return self._data.get("last_run_utc")

    @last_run_utc.setter
    def last_run_utc(self, value: Optional[str]) -> None:
        self._data["last_run_utc"] = value
