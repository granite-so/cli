from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".novps"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API_URL = "https://api.granite.so"


def _restrict_permissions() -> None:
    # The config holds API tokens: owner-only access. Also tightens files
    # written by older versions with the default umask. No-op on Windows.
    try:
        os.chmod(CONFIG_DIR, 0o700)
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    _restrict_permissions()
    return json.loads(CONFIG_FILE.read_text())


def save_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Create the file 0600 up front so the token is never world-readable,
    # not even between write and chmod.
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(config, indent=2) + "\n")
    _restrict_permissions()


def get_token(project: str = "default") -> str | None:
    config = load_config()
    # New format: projects.{alias}.token
    token = config.get("projects", {}).get(project, {}).get("token")
    if token:
        return token
    # Legacy fallback: top-level "token" field for default project only
    if project == "default":
        return config.get("token")
    return None


def get_api_url() -> str:
    return os.environ.get("NOVPS_API_URL") or load_config().get("api_url") or DEFAULT_API_URL


DEFAULT_WS_URL = "wss://websocket.granite.so"


def get_ws_url() -> str:
    return os.environ.get("NOVPS_WS_URL") or load_config().get("ws_url") or DEFAULT_WS_URL
