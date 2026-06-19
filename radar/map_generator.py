"""Generate a static Leaflet + OpenStreetMap map of upcoming events.

Writes a single self-contained ``docs/index.html`` (Leaflet from a CDN, OSM
tiles — no API keys). Pins are sized by popularity (attendee_count) and
coloured by category; popups show details, a Google Maps link and the
"I'm going" count. Events with a positive going-count also appear on a
toggleable personal layer.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .messages import maps_url, fmt_price
from .models import Event
from .scoring import category_emoji
from .state import State

log = logging.getLogger(__name__)


def _color_for(category: str) -> str:
    palette = {
        "halal": "#2e7d32",
        "hiking": "#6d4c41",
        "horses": "#8d6e63",
        "language_exchange": "#1565c0",
        "tennis": "#c0ca33",
        "sports": "#0277bd",
        "fireworks": "#d81b60",
        "festival": "#f4511e",
        "tech": "#5e35b1",
        "mystery": "#7b1fa2",
        "nightlife": "#ad1457",
        "tourguide": "#00838f",
    }
    return palette.get(category, "#455a64")


def _event_to_marker(event: Event, cfg: Config, going: int) -> dict[str, Any]:
    when = event.start_dt.strftime("%a %d %b %Y, %H:%M") if event.start_dt else "Date TBA"
    return {
        "lat": event.lat,
        "lng": event.lng,
        "title": event.title,
        "emoji": category_emoji(event, cfg),
        "color": _color_for(event.category),
        "category": event.category or "other",
        "when": when,
        "venue": event.venue or event.address,
        "price": fmt_price(event.price),
        "url": event.url,
        "maps": maps_url(event),
        "attendees": event.attendee_count,
        "going": going,
        "radius": _radius(event.attendee_count),
    }


def _radius(attendees: int) -> int:
    if attendees >= 10000:
        return 18
    if attendees >= 2000:
        return 14
    if attendees >= 500:
        return 11
    if attendees >= 50:
        return 9
    return 7


def generate_map(events: list[Event], cfg: Config, state: State) -> Path:
    """Render the map HTML and return the output path."""
    map_cfg = cfg.get("map", default={}) or {}
    output = Path(cfg.root) / map_cfg.get("output", "docs/index.html")
    output.parent.mkdir(parents=True, exist_ok=True)

    markers = [
        _event_to_marker(e, cfg, state.going_count(e.id))
        for e in events
        if e.lat is not None and e.lng is not None
    ]
    center = map_cfg.get("center", [34.6863, 135.5200])
    zoom = int(map_cfg.get("zoom", 9))
    title = map_cfg.get("title", "Kansai Radar — Upcoming Events")
    # Use the last data-collection time (not "now") so the page only changes
    # when the data does — avoids an empty commit on every frequent poll run.
    stamp = state.last_collect_utc
    if stamp:
        try:
            generated = datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M JST")
        except ValueError:
            generated = stamp
    else:
        generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html_doc = _TEMPLATE.format(
        title=html.escape(title),
        center=json.dumps(center),
        zoom=zoom,
        markers=json.dumps(markers, ensure_ascii=False),
        generated=generated,
        count=len(markers),
    )
    output.write_text(html_doc, encoding="utf-8")
    log.info("Wrote map with %d markers to %s", len(markers), output)
    return output


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <style>
    html, body {{ margin: 0; height: 100%; font-family: system-ui, sans-serif; }}
    #map {{ height: 100%; width: 100%; }}
    .banner {{ position: absolute; z-index: 1000; top: 10px; left: 50px;
      background: rgba(255,255,255,0.92); padding: 6px 12px; border-radius: 8px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 14px; }}
    .banner b {{ color: #1565c0; }}
    .popup-title {{ font-size: 15px; font-weight: 600; }}
    .popup-row {{ margin-top: 3px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="banner">🛰 <b>{title}</b> — {count} events · updated {generated}</div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
    var markers = {markers};
    var map = L.map('map').setView({center}, {zoom});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }}).addTo(map);

    var allLayer = L.layerGroup().addTo(map);
    var goingLayer = L.layerGroup();

    function esc(s) {{ return (s || '').replace(/[&<>"]/g, function(c) {{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]; }}); }}

    markers.forEach(function(m) {{
      var popup = '<div class="popup-title">' + esc(m.emoji) + ' ' + esc(m.title) + '</div>' +
        '<div class="popup-row">🗓 ' + esc(m.when) + '</div>' +
        (m.venue ? '<div class="popup-row">📍 ' + esc(m.venue) + '</div>' : '') +
        '<div class="popup-row">💴 ' + esc(m.price) + '</div>' +
        (m.attendees ? '<div class="popup-row">👥 ' + m.attendees + ' expected</div>' : '') +
        (m.going ? '<div class="popup-row">🙋 ' + m.going + ' going</div>' : '') +
        '<div class="popup-row">' +
          (m.url ? '<a href="' + esc(m.url) + '" target="_blank">Source</a> · ' : '') +
          '<a href="' + esc(m.maps) + '" target="_blank">Google Maps</a></div>';
      var marker = L.circleMarker([m.lat, m.lng], {{
        radius: m.radius, color: m.color, fillColor: m.color,
        fillOpacity: 0.75, weight: 1.5
      }}).bindPopup(popup);
      marker.addTo(allLayer);
      if (m.going > 0) {{ marker.addTo(goingLayer); }}
    }});

    L.control.layers(null, {{
      'All events': allLayer,
      "I'm going": goingLayer
    }}, {{ collapsed: false }}).addTo(map);
  </script>
</body>
</html>
"""
