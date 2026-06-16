"""Core data model: the normalized :class:`Event`."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional

from dateutil import parser as date_parser


def _slugify(text: str) -> str:
    """Reduce arbitrary text to a stable, comparable token."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


@dataclass
class Event:
    """A normalized event.

    Mirrors the project data schema. ``id`` is derived deterministically from
    the source, title and start time so the same event from the same source
    always collapses to one record across runs.
    """

    title: str
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    venue: str = ""
    address: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    price: str = "unknown"  # "free" / an amount string / "unknown"
    contact: str = ""
    source: str = ""
    url: str = ""
    description: str = ""
    attendee_count: int = 0

    # Derived / pipeline fields (not part of the raw schema but persisted).
    id: str = ""
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    category: str = ""
    major: bool = False
    notified: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.compute_id()

    def compute_id(self) -> str:
        """Deterministic id from source + title + start date."""
        day = self.start_dt.date().isoformat() if self.start_dt else "nodate"
        basis = f"{self.source}|{_slugify(self.title)}|{day}".encode("utf-8")
        return hashlib.sha1(basis).hexdigest()[:16]

    @property
    def searchable_text(self) -> str:
        """Concatenated lower-cased text used for keyword scoring."""
        parts = [self.title, self.description, self.venue, " ".join(self.tags)]
        return " ".join(p for p in parts if p).lower()

    @property
    def location_query(self) -> str:
        """Best free-text string to hand to the geocoder."""
        return self.address or self.venue

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation (datetimes as ISO strings)."""
        data = asdict(self)
        data["start_dt"] = self.start_dt.isoformat() if self.start_dt else None
        data["end_dt"] = self.end_dt.isoformat() if self.end_dt else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Rebuild an Event from its persisted dict form."""
        data = dict(data)
        for key in ("start_dt", "end_dt"):
            value = data.get(key)
            data[key] = _parse_dt(value) if value else None
        # Tolerate unknown/extra keys from older state files.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a variety of date/datetime inputs into a datetime, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
