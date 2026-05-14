"""Persistent storage for the Reon's bond token.

The token lives in a per-user config dir, NOT next to the package files (which
would be inside site-packages for an installed copy). On Windows that's
``%APPDATA%\\reon\\token.json``, on POSIX ``~/.config/reon/token.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "reon"


def token_path() -> Path:
    return config_dir() / "token.json"


@dataclass
class StoredToken:
    mac: str
    token: bytes
    paired_at: datetime


def load() -> StoredToken | None:
    p = token_path()
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return StoredToken(
        mac=data["mac"],
        token=bytes.fromhex(data["auth_token_hex"]),
        paired_at=datetime.fromisoformat(data["paired_at"]),
    )


def save(mac: str, token: bytes) -> Path:
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "mac": mac,
        "auth_token_hex": token.hex(),
        "paired_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))
    return p
