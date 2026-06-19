"""End-to-end orchestration of a single radar run.

Steps (each isolated so a failure degrades gracefully):
  1. Collect events from all enabled sources.
  2. Score against the local interest profile; keep the relevant ones.
  3. Geocode (cached) and upsert kept events into state.
  4. Purge events that have ended (retention window) so state stays minimal.
  5. Re-load the current kept/upcoming set (re-scored against live config).
  6. Send the morning digest (at most once per JST day).
  7. Fire any due reminders and record their notified flags.
  8. Regenerate the public Leaflet map.
  9. Process any pending Telegram commands.
  10. Persist state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .commands import process_commands
from .config import Config
from .dedupe import dedupe
from .geocode import Geocoder
from .map_generator import generate_map
from .messages import format_digest, format_reminder
from .models import Event
from .reminders import due_reminders
from .scoring import is_relevant, score_event
from .sources import collect_all
from .state import State
from .telegram import TelegramClient

log = logging.getLogger(__name__)


@dataclass
class RunOptions:
    dry_run: bool = False
    force_digest: bool = False
    skip_collect: bool = False
    skip_commands: bool = False  # set in --serve mode (commands handled live)


def run(cfg: Config, state: State, opts: RunOptions) -> None:
    """Execute one full radar cycle."""
    tz = cfg.tz
    now = datetime.now(tz)
    tg = TelegramClient(
        token=cfg.telegram_secrets.token,
        chat_id=cfg.telegram_secrets.chat_id,
        api_base=cfg.get("telegram", "api_base", default="https://api.telegram.org"),
        dry_run=opts.dry_run,
    )
    if not tg.configured and not opts.dry_run:
        log.warning(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; messages will print only."
        )

    # 1-3. Collect, score, geocode, persist kept events.
    if not opts.skip_collect:
        _ingest(cfg, state)

    # 4. Purge ended events.
    _cleanup(cfg, state, now)

    # 5. Current kept/upcoming set (re-scored against live config).
    kept = _current_kept(cfg, state, now)
    log.info("%d kept upcoming events", len(kept))

    # 6. Morning digest.
    _maybe_send_digest(cfg, state, tg, kept, now, opts)

    # 7. Reminders.
    _send_reminders(cfg, state, tg, kept, now)

    # 8. Map.
    try:
        generate_map(kept, cfg, state)
    except Exception as exc:  # noqa: BLE001
        log.exception("Map generation failed: %s", exc)

    # 9. Commands (skipped in --serve mode, where they are handled live).
    if not opts.skip_commands:
        try:
            process_commands(tg, cfg, state, kept)
        except Exception as exc:  # noqa: BLE001
            log.exception("Command processing failed: %s", exc)

    # 10. Persist.
    state.last_run_utc = datetime.utcnow().isoformat()
    state.save()


def kept_upcoming(cfg: Config, state: State, now: Optional[datetime] = None) -> list[Event]:
    """Public helper: the current kept/upcoming events (used by --serve)."""
    return _current_kept(cfg, state, now or datetime.now(cfg.tz))


# ---------------------------------------------------------------------------


def _ingest(cfg: Config, state: State) -> None:
    raw = collect_all(cfg)
    deduped = dedupe(raw)
    geocoder = Geocoder(cfg, state)
    now_iso = datetime.utcnow().isoformat()
    kept = 0
    for event in deduped:
        score_event(event, cfg)
        if not is_relevant(event, cfg):
            continue
        geocoder.enrich(event)
        if not event.first_seen:
            event.first_seen = now_iso
        state.upsert_event(event)
        kept += 1
    log.info("Ingested %d relevant events into state", kept)


def _cleanup(cfg: Config, state: State, now: datetime) -> None:
    """Purge dated events past their retention window and expired leads."""
    cutoff = now - timedelta(days=cfg.retention_days)
    lead_cutoff = now - timedelta(days=cfg.lead_retention_days)
    removed = 0
    for event in state.all_events():
        ref = event.end_dt or event.start_dt
        if ref is None:
            # Date-less lead: expire by first-seen age instead.
            if _lead_expired(event, lead_cutoff, cfg.tz):
                state.remove_event(event.id)
                removed += 1
            continue
        ref_aware = ref.replace(tzinfo=cfg.tz) if ref.tzinfo is None else ref
        if ref_aware < cutoff:
            state.remove_event(event.id)
            removed += 1
    if removed:
        log.info("Purged %d past/expired events", removed)


def _lead_expired(event: Event, cutoff: datetime, tz) -> bool:
    if not event.first_seen:
        return False  # stamped on next ingest; keep for now
    seen = _parse_iso(event.first_seen, tz)
    return seen is not None and seen < cutoff


def _parse_iso(value: str, tz) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def _current_kept(cfg: Config, state: State, now: datetime) -> list[Event]:
    kept: list[Event] = []
    horizon = now - timedelta(hours=1)
    for event in state.all_events():
        score_event(event, cfg)  # re-score against current config
        if not is_relevant(event, cfg):
            continue
        start = event.start_dt
        if start is not None:
            start_aware = start.replace(tzinfo=cfg.tz) if start.tzinfo is None else start
            if start_aware < horizon:
                continue
        state.upsert_event(event)  # persist refreshed scoring
        kept.append(event)
    return kept


def _maybe_send_digest(
    cfg: Config,
    state: State,
    tg: TelegramClient,
    kept: list[Event],
    now: datetime,
    opts: RunOptions,
) -> None:
    today = now.date().isoformat()
    digest_hour = int(cfg.get("telegram", "digest_hour", default=7))

    if not opts.force_digest:
        if state.last_digest_date == today:
            log.info("Digest already sent today (%s); skipping", today)
            return
        if now.hour < digest_hour:
            log.info("Before digest hour (%d); skipping digest", digest_hour)
            return

    todays = [e for e in kept if _same_day(e, now, cfg.tz)]
    # Date-less leads (e.g. fresh RSS articles) shown once, then flagged.
    leads = [
        e for e in kept if e.start_dt is None and not e.notified.get("digest_lead")
    ]
    map_url = cfg.get("telegram", "map_public_url", default="")
    going = {e.id: state.going_count(e.id) for e in todays}
    text = format_digest(todays, cfg, going, map_url, leads=leads)
    # Attach the persistent button keyboard so the user always has quick taps.
    from .messages import main_reply_keyboard

    tg.send_message(text, reply_markup=main_reply_keyboard())
    for lead in leads:
        lead.notified["digest_lead"] = True
        state.upsert_event(lead)
    state.last_digest_date = today
    log.info("Sent digest: %d dated event(s), %d lead(s)", len(todays), len(leads))


def _send_reminders(
    cfg: Config,
    state: State,
    tg: TelegramClient,
    kept: list[Event],
    now: datetime,
) -> None:
    for event, tier in due_reminders(kept, cfg, now):
        going = state.going_count(event.id)
        tg.send_message(format_reminder(event, cfg, tier, going))
        event.notified[tier] = True
        state.upsert_event(event)
        log.info("Sent %s reminder for %r", tier, event.title)


def _same_day(event: Event, now: datetime, tz) -> bool:
    dt = event.start_dt
    if dt is None:
        return False
    dt_aware = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    return dt_aware.date() == now.date()
