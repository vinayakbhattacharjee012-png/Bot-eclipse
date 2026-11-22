"""Lazy handler registry. A heavy feature module is imported the first time it
is needed, never at startup."""
from __future__ import annotations

import importlib
from types import ModuleType

_HANDLERS: dict[str, str] = {
    "ai": "utils.ai_client",
    "akinator": "utils.akinator_engine",
    "anicatch": "utils.anicatch_engine",
    "automod": "utils.automod_rules",
    "music": "utils.music_queue",
}
_loaded: dict[str, ModuleType] = {}


def get(name: str) -> ModuleType:
    """Return a handler module, importing it on first use."""
    if name not in _HANDLERS:
        raise KeyError(f"no handler registered as {name!r}")
    if name not in _loaded:
        _loaded[name] = importlib.import_module(_HANDLERS[name])
    return _loaded[name]


def registered() -> tuple[str, ...]:
    return tuple(_HANDLERS)


def loaded() -> tuple[str, ...]:
    return tuple(n for n in _HANDLERS if n in _loaded)
