"""Best-effort keyless event discovery via DuckDuckGo HTML results.

Off by default. This does NOT scrape social networks and creates no accounts;
it only reads DuckDuckGo's public HTML endpoint to surface candidate event
pages as low-confidence leads. Results are coarse and meant to be combined with
the keyword scorer, which filters out the noise.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Config
from ..models import Event
from .base import http_get

log = logging.getLogger(__name__)


def collect(cfg: Config) -> list[Event]:
    sc = cfg.source_cfg("duckduckgo")
    html_url: str = sc.get("html_url", "https://html.duckduckgo.com/html/")
    queries: list[str] = sc.get("queries", []) or []
    max_results: int = int(sc.get("max_results", 10))

    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        log.warning("beautifulsoup4 not installed; skipping DuckDuckGo discovery")
        return []

    events: list[Event] = []
    for query in queries:
        resp = http_get(html_url, params={"q": query})
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for result in soup.select(".result__a")[:max_results]:
            title = result.get_text(strip=True)
            href = result.get("href", "")
            if not title or not href:
                continue
            events.append(
                Event(
                    title=title,
                    start_dt=None,  # discovery leads have no reliable date
                    tags=["discovery", "ddg", "lead"],
                    source="duckduckgo",
                    url=href,
                    description=f"Discovery lead for query: {query}",
                )
            )
    return events
