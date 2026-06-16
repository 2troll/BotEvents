"""Optional interactivity via getUpdates polling (no server required).

Each scheduled run pulls any pending messages and processes simple commands:

  /hoy            — events happening today
  /semana         — events in the next 7 days
  /<tag>          — events matching an interest tag (e.g. /halal, /tech)
  /mapa           — link to the live map
  /voy <event_id> — mark "I'm going"; rendered on the map's personal layer

The Telegram update offset is persisted in state so each message is handled
exactly once. This is intentionally separate from the autonomous push.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .messages import format_event_line
from .models import Event
from .state import State
from .telegram import TelegramClient

log = logging.getLogger(__name__)


def process_commands(
    tg: TelegramClient,
    cfg: Config,
    state: State,
    kept_events: list[Event],
) -> None:
    """Poll for and respond to user commands."""
    if not cfg.get("telegram", "commands_enabled", default=True):
        return

    updates = tg.get_updates(offset=state.telegram_offset)
    if not updates:
        return

    valid_tags = {i.get("tag") for i in cfg.interests}
    map_url = cfg.get("telegram", "map_public_url", default="")
    by_id = {e.id: e for e in kept_events}

    for update in updates:
        state.telegram_offset = update["update_id"] + 1
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        user = message.get("from", {})
        who = user.get("username") or str(user.get("id", "anon"))
        if not text.startswith("/"):
            continue

        parts = text.split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        reply = _handle(cmd, arg, cfg, state, kept_events, valid_tags, map_url, by_id, who)
        if reply:
            tg.send_message(reply, chat_id=chat_id)


def _handle(
    cmd: str,
    arg: str,
    cfg: Config,
    state: State,
    kept: list[Event],
    valid_tags: set,
    map_url: str,
    by_id: dict[str, Event],
    who: str,
) -> str:
    tz = cfg.tz
    now = datetime.now(tz)

    if cmd in ("start", "help"):
        return _help_text(valid_tags)

    if cmd == "mapa":
        return f"🗺 Live event map: {map_url}" if map_url else "Map URL not configured yet."

    if cmd == "hoy":
        today = [e for e in kept if _on_day(e, now, tz, 0)]
        return _list("📣 Today", today, cfg)

    if cmd == "semana":
        week = [e for e in kept if _within_days(e, now, tz, 7)]
        return _list("🗓 Next 7 days", week, cfg)

    if cmd == "voy":
        if not arg:
            return "Usage: /voy <event_id>"
        if arg not in by_id:
            return f"Unknown event id: {arg}"
        count = state.mark_going(arg, who)
        return f"✅ Marked you as going to “{by_id[arg].title}”. {count} going now."

    if cmd in valid_tags:
        tagged = [e for e in kept if cmd in e.matched]
        return _list(f"#{cmd}", tagged, cfg)

    return "Unknown command. Try /help"


def _help_text(valid_tags: set) -> str:
    tags = ", ".join(f"/{t}" for t in sorted(valid_tags))
    return (
        "🛰 <b>Kansai Radar</b> commands:\n"
        "/hoy — today's events\n"
        "/semana — next 7 days\n"
        "/mapa — live map link\n"
        "/voy &lt;event_id&gt; — mark I'm going\n"
        f"interest tags: {tags}"
    )


def _list(header: str, events: list[Event], cfg: Config) -> str:
    if not events:
        return f"{header}: nothing matching right now. 🌙"
    blocks = [f"<b>{header}</b>"]
    for event in sorted(events, key=lambda e: e.start_dt or datetime.max):
        blocks.append(format_event_line(event, cfg))
    return "\n\n".join(blocks)


def _localize(event: Event, tz):
    dt = event.start_dt
    if dt is None:
        return None
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def _on_day(event: Event, now: datetime, tz, offset: int) -> bool:
    dt = _localize(event, tz)
    return dt is not None and dt.date() == (now + timedelta(days=offset)).date()


def _within_days(event: Event, now: datetime, tz, days: int) -> bool:
    dt = _localize(event, tz)
    return dt is not None and now.date() <= dt.date() <= (now + timedelta(days=days)).date()
