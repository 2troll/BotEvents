"""Always-on long-polling mode for instant command replies.

Run with ``python -m radar --serve`` on any free 24/7 host (e.g. a Telegram-bot
host such as Pella or JustRunMy.App). In this mode the bot:

- Long-polls Telegram and answers commands / button taps **instantly**.
- Periodically (every ``--serve-interval`` seconds) runs the full autonomous
  pipeline: collect events, send the morning digest (once-per-day gated), fire
  reminders, and regenerate the map.
- Optionally pushes ``state.json`` and ``docs/index.html`` back to GitHub (when
  ``GITHUB_TOKEN``/``GITHUB_REPO`` are set) so state is durable and the public
  Pages map stays fresh.

This is a single-threaded loop: ``getUpdates`` long-polls (~20 s) for snappy
replies, and the pipeline is interleaved on the interval. Use this OR GitHub
Actions for command handling — not both at once (Telegram allows only one
``getUpdates`` consumer).
"""

from __future__ import annotations

import logging
import time

from . import github_sync
from .commands import BOT_COMMANDS, build_context, dispatch_update
from .config import Config
from .pipeline import RunOptions, kept_upcoming, run
from .state import State
from .telegram import TelegramClient

log = logging.getLogger(__name__)

POLL_TIMEOUT = 20  # seconds for Telegram long-polling


def serve(cfg: Config, state_path: str, interval: int) -> int:
    """Run the always-on loop. Returns a process exit code."""
    tg = TelegramClient(
        token=cfg.telegram_secrets.token,
        chat_id=cfg.telegram_secrets.chat_id,
        api_base=cfg.get("telegram", "api_base", default="https://api.telegram.org"),
        dry_run=False,
    )
    if not tg.configured:
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID required for --serve mode.")
        return 2

    tg.set_my_commands(BOT_COMMANDS)
    state = State.load(state_path)
    offset = state.telegram_offset
    kept: list = []
    next_pipeline = 0.0

    log.info(
        "Serve mode started (pipeline every %ss, GitHub sync %s).",
        interval,
        "on" if github_sync.enabled() else "off",
    )
    while True:
        try:
            # Periodic autonomous pipeline (collect/digest/reminders/map).
            if time.monotonic() >= next_pipeline:
                run(cfg, state, RunOptions(skip_commands=True))
                kept = kept_upcoming(cfg, state)
                offset = max(offset, state.telegram_offset)
                if github_sync.enabled():
                    github_sync.push_paths(
                        [state_path, cfg.get("map", "output", default="docs/index.html")],
                        "chore: radar serve update [skip ci]",
                    )
                next_pipeline = time.monotonic() + interval

            # Long-poll for commands / button taps and handle them instantly.
            ctx = build_context(cfg, state, kept)
            updates = tg.get_updates(offset=offset, timeout=POLL_TIMEOUT)
            for update in updates:
                offset = update["update_id"] + 1
                dispatch_update(tg, ctx, update)
            if updates:
                state.telegram_offset = offset
                state.save()
        except KeyboardInterrupt:  # pragma: no cover
            log.info("Serve mode stopped.")
            return 0
        except Exception as exc:  # noqa: BLE001 - never crash the long-lived loop
            log.exception("Serve loop error (continuing): %s", exc)
            time.sleep(5)
