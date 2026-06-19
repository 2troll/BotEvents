"""Optional interactivity via getUpdates polling (no server required).

Each scheduled run pulls pending updates and processes:

  Slash commands  /hoy /semana /<tag> /mapa /major /menu /voy <id> /ayuda
  Button taps     the persistent bottom keyboard + inline buttons
  Callbacks       "🙋 Voy", interest filters, and menu actions

Because this is serverless (polling on a schedule), replies arrive on the next
scheduled run, not instantly. The Telegram update offset is persisted in state
so each update is handled exactly once.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import Config
from .messages import (
    LABEL_TO_COMMAND,
    event_inline_keyboard,
    format_event_line,
    main_reply_keyboard,
    maps_url,
    menu_inline_keyboard,
)
from .models import Event
from .state import State
from .telegram import TelegramClient

log = logging.getLogger(__name__)

# Max event cards sent per command reply (keeps message volume sane).
MAX_CARDS = 10

# Slash-command menu shown by Telegram's "/" button.
BOT_COMMANDS = [
    {"command": "hoy", "description": "Eventos de hoy"},
    {"command": "semana", "description": "Próximos 7 días"},
    {"command": "major", "description": "Eventos grandes ⭐"},
    {"command": "mapa", "description": "Mapa en vivo 🗺"},
    {"command": "menu", "description": "Menú de botones 📋"},
    {"command": "ayuda", "description": "Cómo usar el bot"},
]


def process_commands(
    tg: TelegramClient,
    cfg: Config,
    state: State,
    kept_events: list[Event],
) -> None:
    """Poll for and respond to user commands and button taps."""
    if not cfg.get("telegram", "commands_enabled", default=True):
        return

    tg.set_my_commands(BOT_COMMANDS)  # idempotent; keeps the "/" menu fresh

    updates = tg.get_updates(offset=state.telegram_offset)
    if not updates:
        return

    ctx = _Context(cfg, state, kept_events)
    for update in updates:
        state.telegram_offset = update["update_id"] + 1
        try:
            if "callback_query" in update:
                _handle_callback(tg, ctx, update["callback_query"])
            elif "message" in update:
                _handle_message(tg, ctx, update["message"])
        except Exception as exc:  # noqa: BLE001 - never let one update break the rest
            log.warning("Failed to handle update %s: %s", update.get("update_id"), exc)


class _Context:
    """Shared lookups for one processing pass."""

    def __init__(self, cfg: Config, state: State, kept: list[Event]) -> None:
        self.cfg = cfg
        self.state = state
        self.kept = kept
        self.by_id = {e.id: e for e in kept}
        self.valid_tags = {i.get("tag") for i in cfg.interests}
        self.map_url = cfg.get("telegram", "map_public_url", default="")


# -- message + callback dispatch -------------------------------------------


def _handle_message(tg: TelegramClient, ctx: _Context, message: dict[str, Any]) -> None:
    text = (message.get("text") or "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))
    who = _who(message.get("from", {}))
    if not text:
        return

    # A tap on the bottom keyboard sends the button's label — map it back.
    if text in LABEL_TO_COMMAND:
        cmd, arg = LABEL_TO_COMMAND[text], ""
    elif text.startswith("/"):
        parts = text.split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
    else:
        return  # plain chatter we don't act on

    _run_command(tg, ctx, cmd, arg, chat_id, who)


def _handle_callback(tg: TelegramClient, ctx: _Context, cb: dict[str, Any]) -> None:
    data = cb.get("data", "")
    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    who = _who(cb.get("from", {}))
    kind, _, arg = data.partition(":")

    if kind == "voy":
        event = ctx.by_id.get(arg)
        if event:
            count = ctx.state.mark_going(arg, who)
            tg.answer_callback_query(cb["id"], f"✅ ¡Apuntado! {count} van")
            tg.send_message(
                f"✅ Te apunté a “{event.title}”. Ya van {count}. 🙋",
                chat_id=chat_id,
            )
        else:
            tg.answer_callback_query(cb["id"], "Evento no encontrado")
        return

    if kind == "cmd":
        tg.answer_callback_query(cb["id"])
        _run_command(tg, ctx, arg, "", chat_id, who)
        return

    tg.answer_callback_query(cb["id"])


# -- command implementations ------------------------------------------------


def _run_command(
    tg: TelegramClient,
    ctx: _Context,
    cmd: str,
    arg: str,
    chat_id: str,
    who: str,
) -> None:
    cfg, state = ctx.cfg, ctx.state
    tz = cfg.tz
    now = datetime.now(tz)

    if cmd in ("start", "help", "ayuda"):
        tg.send_message(_help_text(), chat_id=chat_id, reply_markup=main_reply_keyboard())
        return

    if cmd == "menu":
        tg.send_message(
            "📋 <b>Menú</b> — toca una opción:",
            chat_id=chat_id,
            reply_markup=menu_inline_keyboard(cfg, ctx.map_url),
        )
        return

    if cmd == "mapa":
        msg = f"🗺 Mapa de eventos en vivo:\n{ctx.map_url}" if ctx.map_url else "Mapa no configurado todavía."
        tg.send_message(msg, chat_id=chat_id, reply_markup=main_reply_keyboard())
        return

    if cmd == "voy":
        if not arg:
            tg.send_message("Uso: /voy &lt;event_id&gt;", chat_id=chat_id)
        elif arg in ctx.by_id:
            count = state.mark_going(arg, who)
            tg.send_message(
                f"✅ Te apunté a “{ctx.by_id[arg].title}”. Ya van {count}. 🙋",
                chat_id=chat_id,
            )
        else:
            tg.send_message(f"No encuentro ese evento: {arg}", chat_id=chat_id)
        return

    if cmd == "hoy":
        events = [e for e in ctx.kept if _on_day(e, now, tz, 0)]
        _send_event_list(tg, ctx, "📅 Eventos de hoy", events, chat_id)
        return

    if cmd == "semana":
        events = [e for e in ctx.kept if _within_days(e, now, tz, 7)]
        _send_event_list(tg, ctx, "🗓 Próximos 7 días", events, chat_id)
        return

    if cmd in ("major", "grandes"):
        events = [e for e in ctx.kept if e.major and e.start_dt]
        _send_event_list(tg, ctx, "⭐ Eventos grandes", events, chat_id)
        return

    if cmd in ctx.valid_tags:
        events = [e for e in ctx.kept if cmd in e.matched]
        _send_event_list(tg, ctx, f"#{cmd}", events, chat_id)
        return

    tg.send_message(
        "🤔 No conozco ese comando. Toca 📋 Menú o /ayuda.",
        chat_id=chat_id,
        reply_markup=main_reply_keyboard(),
    )


def _send_event_list(
    tg: TelegramClient,
    ctx: _Context,
    header: str,
    events: list[Event],
    chat_id: str,
) -> None:
    """Send a header (with the bottom keyboard) then one card per event with
    its own inline buttons (🙋 Voy / 🗺 Mapa / 🔗 Info)."""
    events = sorted(events, key=lambda e: e.start_dt or datetime.max)
    if not events:
        tg.send_message(
            f"{header}: nada por ahora. 🌙\nProba /semana o el 📋 Menú.",
            chat_id=chat_id,
            reply_markup=main_reply_keyboard(),
        )
        return

    shown = events[:MAX_CARDS]
    suffix = "" if len(events) <= MAX_CARDS else f"  (+{len(events) - MAX_CARDS} más)"
    tg.send_message(
        f"<b>{header}</b> — {len(events)} evento(s){suffix}",
        chat_id=chat_id,
        reply_markup=main_reply_keyboard(),
    )
    for event in shown:
        going = ctx.state.going_count(event.id)
        tg.send_message(
            format_event_line(event, ctx.cfg, going),
            chat_id=chat_id,
            reply_markup=event_inline_keyboard(event, maps_url(event)),
        )


def _help_text() -> str:
    return (
        "🛰 <b>Kansai Radar</b>\n\n"
        "Toca los botones de abajo 👇 o usa estos comandos:\n"
        "📅 /hoy — eventos de hoy\n"
        "🗓 /semana — próximos 7 días\n"
        "⭐ /major — eventos grandes\n"
        "🗺 /mapa — mapa en vivo\n"
        "📋 /menu — menú con botones\n"
        "🏷 /halal /tech /fireworks … — por interés\n"
        "🙋 /voy &lt;id&gt; — apuntarte a un evento\n\n"
        "Cada evento trae botones <b>🙋 Voy</b>, <b>🗺 Mapa</b> y <b>🔗 Info</b>.\n"
        "<i>Nota: las respuestas llegan en la siguiente pasada del bot, no son instantáneas.</i>"
    )


# -- helpers ----------------------------------------------------------------


def _who(user: dict[str, Any]) -> str:
    return user.get("username") or str(user.get("id", "anon"))


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
