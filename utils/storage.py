"""Tiny async-safe JSON data store.

Everything lives in one data/store.json file, one lock guards all writes,
and every save goes to a temp file first then an atomic rename -- so a
crash mid-write can never leave you with a corrupted file.

Not built for huge servers with tens of thousands of members doing heavy
writes every second, but for a normal community server it's simple,
dependency-free and good enough.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "store.json"

_DEFAULT: dict[str, Any] = {
    "guilds": {},  # guild_id (str) -> per-guild data, see _default_guild()
}


def _default_guild() -> dict[str, Any]:
    return {
        "config": {
            "log_channel_id": None,
            "level_up_channel_id": None,
            "verification_channel_id": None,
            "verification_role_id": None,
            "verification_message_id": None,
            "antispam_enabled": True,
            "antispam_max_messages": 5,
            "antispam_window_seconds": 5,
            "antispam_timeout_seconds": 60,
            "antiraid_enabled": True,
            "antiraid_join_threshold": 6,
            "antiraid_window_seconds": 10,
            "antiraid_min_account_age_hours": 24,
        },
        "levels": {},       # user_id (str) -> {"xp": int, "level": int}
        "level_roles": {},  # level (str) -> role_id
        "warnings": {},     # user_id (str) -> [ {"reason", "moderator_id", "timestamp"} ]
        "reaction_roles": {},  # message_id (str) -> { emoji (str): role_id }
        "afk": {},          # user_id (str) -> {"reason": str, "timestamp": float}
    }


class Storage:
    def __init__(self, path: Path = DATA_PATH) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupt or unreadable file: back it up and start fresh
                # rather than crashing the whole bot on startup.
                backup = self.path.with_suffix(".json.bak")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                self._data = dict(_DEFAULT)
        else:
            self._data = dict(_DEFAULT)
        self._data.setdefault("guilds", {})

    def _save_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, prefix=".store_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    async def save(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_sync)

    def guild(self, guild_id: int) -> dict[str, Any]:
        """Get (creating if needed) the data dict for one guild. Caller must
        call `await store.save()` after mutating it."""
        key = str(guild_id)
        if key not in self._data["guilds"]:
            self._data["guilds"][key] = _default_guild()
        else:
            # Fill in any config keys added in later versions of the bot.
            defaults = _default_guild()
            g = self._data["guilds"][key]
            for section in ("config",):
                g.setdefault(section, {})
                for k, v in defaults[section].items():
                    g[section].setdefault(k, v)
            for section in ("levels", "level_roles", "warnings", "reaction_roles", "afk"):
                g.setdefault(section, defaults[section])
        return self._data["guilds"][key]


store = Storage()
