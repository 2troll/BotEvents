"""Public HTML listing-page collector (requests + BeautifulSoup).

Each configured page describes, via CSS selectors, how to locate event rows and
their sub-fields. This keeps the parser fully data-driven: adding a new site is
a config change, not a code change. Respect each site's robots.txt and ToS.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urljoin

from ..config import Config
from ..models import Event
from .base import http_get, parse_datetime

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("html")
    pages: list[dict[str, Any]] = sc.get("pages", []) or []
    events: list[Event] = []
    for page in pages:
        try:
            events.extend(_parse_page(page))
        except Exception as exc:  # noqa: BLE001 - isolate per-page failures
            log.warning("HTML page failed %s: %s", page.get("url"), exc)
    return events


def _parse_page(page: dict[str, Any]) -> list[Event]:
    url = page.get("url")
    if not url:
        return []
    resp = http_get(url)
    if resp is None:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        log.warning("beautifulsoup4 not installed; skipping HTML pages")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    item_selector = page.get("item_selector", "")
    rows = soup.select(item_selector) if item_selector else []
    events: list[Event] = []
    for row in rows:
        title = _text(row, page.get("title_selector"))
        if not title:
            continue
        link = _attr(row, page.get("link_selector"), "href")
        events.append(
            Event(
                title=title,
                start_dt=parse_datetime(_text(row, page.get("date_selector"))),
                venue=_text(row, page.get("venue_selector")),
                address=_text(row, page.get("venue_selector")),
                tags=["html", page.get("tag", "web")],
                source=page.get("name", "html"),
                url=urljoin(url, link) if link else url,
                description=_text(row, page.get("desc_selector")),
            )
        )
    return events


def _text(row: Any, selector: Optional[str]) -> str:
    if not selector:
        return ""
    el = row.select_one(selector)
    return el.get_text(strip=True) if el else ""


def _attr(row: Any, selector: Optional[str], attr: str) -> str:
    if not selector:
        return ""
    el = row.select_one(selector)
    return el.get(attr, "") if el else ""
