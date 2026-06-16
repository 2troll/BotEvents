"""Shared helpers for source collectors."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests
from dateutil import parser as date_parser

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "KansaiRadar/1.0 (+https://github.com/2troll/botevents) "
        "polite public-event collector"
    ),
    "Accept-Language": "ja,en;q=0.8",
}


def http_get(url: str, **kwargs) -> Optional[requests.Response]:
    """GET with a polite User-Agent and uniform timeout/error handling."""
    headers = {**DEFAULT_HEADERS, **kwargs.pop("headers", {})}
    try:
        resp = requests.get(url, headers=headers, timeout=kwargs.pop("timeout", 25), **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        log.warning("HTTP GET failed for %s: %s", url, exc)
        return None


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Best-effort parse of a date/time string."""
    if not value:
        return None
    try:
        return date_parser.parse(value, fuzzy=True)
    except (ValueError, OverflowError, TypeError):
        return None
