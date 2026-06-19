"""Optional GitHub persistence for --serve mode.

When the bot runs as a long-lived process on a free host (instead of GitHub
Actions), it can push the updated ``state.json`` and ``docs/index.html`` back to
the repository via the GitHub Contents API. This keeps reminder/notified flags
durable across restarts and refreshes the public Pages map.

Activated only when a ``GITHUB_TOKEN`` environment variable is present; without
it the bot still works (state stays local to the host). Configure the target
repo/branch via ``GITHUB_REPO`` (``owner/name``) and ``GITHUB_BRANCH``.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

_API = "https://api.github.com"


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value.strip() if value else None


def enabled() -> bool:
    return bool(_env("GITHUB_TOKEN") and _env("GITHUB_REPO"))


def push_paths(paths: list[str], message: str) -> None:
    """Commit each given file path to the configured repo/branch (best-effort)."""
    token = _env("GITHUB_TOKEN")
    repo = _env("GITHUB_REPO")
    branch = _env("GITHUB_BRANCH") or "main"
    if not token or not repo:
        return
    for path in paths:
        try:
            _put_file(token, repo, branch, path, message)
        except requests.RequestException as exc:
            log.warning("GitHub push failed for %s: %s", path, exc)


def _put_file(token: str, repo: str, branch: str, path: str, message: str) -> None:
    file = Path(path)
    if not file.exists():
        return
    content_b64 = base64.b64encode(file.read_bytes()).decode("ascii")
    url = f"{_API}/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    # Fetch current sha (required to update an existing file).
    sha: Optional[str] = None
    resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=20)
    if resp.status_code == 200:
        sha = resp.json().get("sha")

    payload = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    put = requests.put(url, headers=headers, json=payload, timeout=30)
    put.raise_for_status()
    log.info("Pushed %s to %s@%s", path, repo, branch)
