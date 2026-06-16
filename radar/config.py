"""Configuration loading and typed access.

Reads ``config.yaml`` and overlays secrets from the environment. The rest of
the package accesses configuration through the :class:`Config` wrapper, which
exposes convenience helpers but otherwise keeps the raw dict available.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

log = logging.getLogger(__name__)

# Japan Standard Time. Used as a fallback if the zoneinfo database is missing
# (e.g. minimal CI images) so the bot never hard-depends on tzdata.
JST = timezone(timedelta(hours=9))


@dataclass
class TelegramSecrets:
    """Telegram credentials sourced exclusively from the environment."""

    token: Optional[str]
    chat_id: Optional[str]

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)


class Config:
    """Typed-ish accessor over the parsed YAML config plus env secrets."""

    def __init__(self, data: dict[str, Any], root: Path) -> None:
        self.data = data
        self.root = root
        self.telegram_secrets = TelegramSecrets(
            token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        )

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls, path: str | os.PathLike[str] = "config.yaml") -> "Config":
        cfg_path = Path(path)
        root = cfg_path.resolve().parent
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        log.debug("Loaded config from %s", cfg_path)
        return cls(data, root)

    # -- generic access -----------------------------------------------------

    def get(self, *keys: str, default: Any = None) -> Any:
        """Nested lookup: ``cfg.get("sources", "connpass", "enabled")``."""
        node: Any = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    # -- convenience --------------------------------------------------------

    @property
    def tz(self) -> timezone:
        """Configured timezone, falling back to JST without tzdata."""
        name = self.data.get("timezone", "Asia/Tokyo")
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)  # type: ignore[return-value]
        except Exception:  # pragma: no cover - depends on host tzdata
            log.debug("zoneinfo unavailable for %s; using fixed JST", name)
            return JST

    @property
    def score_threshold(self) -> float:
        return float(self.data.get("score_threshold", 3.0))

    @property
    def interests(self) -> list[dict[str, Any]]:
        return list(self.data.get("interests", []))

    @property
    def major_categories(self) -> set[str]:
        return set(self.data.get("major_categories", []))

    @property
    def major_attendee_threshold(self) -> int:
        return int(self.data.get("major_attendee_threshold", 5000))

    @property
    def retention_days(self) -> int:
        return int(self.data.get("retention_days_after_end", 2))

    def source_cfg(self, name: str) -> dict[str, Any]:
        return self.get("sources", name, default={}) or {}

    def source_enabled(self, name: str) -> bool:
        return bool(self.source_cfg(name).get("enabled", False))
