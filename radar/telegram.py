"""Thin Telegram Bot API client over plain HTTPS (no SDK).

Supports sending messages (auto-splitting on the 4096-char limit) and polling
``getUpdates`` for simple slash commands. In ``dry_run`` mode every outbound
message is printed instead of sent, so the whole pipeline is testable offline.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

# Telegram hard limit per message; leave headroom for safety.
MAX_MESSAGE_LEN = 4000


class TelegramClient:
    """Minimal Telegram Bot API wrapper."""

    def __init__(
        self,
        token: Optional[str],
        chat_id: Optional[str],
        api_base: str = "https://api.telegram.org",
        dry_run: bool = False,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.api_base = api_base.rstrip("/")
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    # -- sending ------------------------------------------------------------

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        disable_preview: bool = True,
        reply_markup: Optional[dict] = None,
    ) -> None:
        """Send ``text``, splitting into multiple messages when too long.

        ``reply_markup`` (an inline/reply keyboard) is attached to the LAST
        chunk only, so buttons appear once beneath the full message.
        """
        target = chat_id or self.chat_id
        chunks = _split_message(text)
        for index, chunk in enumerate(chunks):
            markup = reply_markup if index == len(chunks) - 1 else None
            self._send_chunk(chunk, target, disable_preview, markup)

    def _send_chunk(
        self,
        text: str,
        chat_id: Optional[str],
        disable_preview: bool,
        reply_markup: Optional[dict] = None,
    ) -> None:
        if self.dry_run or not self.configured:
            prefix = "[dry-run] " if self.dry_run else "[telegram-not-configured] "
            buttons = f"\n[buttons: {reply_markup}]" if reply_markup else ""
            print(f"\n{prefix}--- message to {chat_id} ---\n{text}{buttons}\n")
            return
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = requests.post(self._url("sendMessage"), json=payload, timeout=30)
            if resp.status_code == 429:
                retry = resp.json().get("parameters", {}).get("retry_after", 2)
                log.warning("Rate limited by Telegram; sleeping %ss", retry)
                time.sleep(float(retry) + 0.5)
                resp = requests.post(self._url("sendMessage"), json=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("Failed to send Telegram message: %s", exc)

    def answer_callback_query(self, callback_id: str, text: str = "") -> None:
        """Acknowledge a button tap (shows a small toast in the client)."""
        if self.dry_run or not self.configured:
            return
        try:
            requests.post(
                self._url("answerCallbackQuery"),
                json={"callback_query_id": callback_id, "text": text},
                timeout=15,
            )
        except requests.RequestException as exc:
            log.warning("answerCallbackQuery failed: %s", exc)

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        """Register the slash-command menu shown by the Telegram '/' button."""
        if self.dry_run or not self.configured:
            return
        try:
            requests.post(
                self._url("setMyCommands"),
                json={"commands": commands},
                timeout=15,
            )
        except requests.RequestException as exc:
            log.warning("setMyCommands failed: %s", exc)

    # -- receiving (commands) ----------------------------------------------

    def get_updates(self, offset: int = 0, timeout: int = 0) -> list[dict[str, Any]]:
        """Fetch pending updates (messages and button taps). Empty on dry-run."""
        if self.dry_run or not self.configured:
            return []
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        try:
            resp = requests.get(self._url("getUpdates"), params=params, timeout=timeout + 20)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", []) if data.get("ok") else []
        except (requests.RequestException, ValueError) as exc:
            log.warning("getUpdates failed: %s", exc)
            return []


def _split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split text on line boundaries so no chunk exceeds the limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # A single overly-long line is hard-split.
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks
