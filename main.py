"""Convenience entry point for one-click bot hosts (Pella, JustRunMy.App, …).

Many free Telegram-bot hosts simply run ``main.py``. This starts the always-on
serve loop, so button taps and commands are answered instantly.

Equivalent to:  python -m radar --serve

Required environment variables on the host:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Optional (keeps the public map fresh + state durable across restarts):
  GITHUB_TOKEN, GITHUB_REPO (owner/name), GITHUB_BRANCH
"""

import sys

from radar.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["--serve"]))
