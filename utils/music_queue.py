"""Music queue and an honest playback status report.

The queue stores requested track titles only. Nothing is resolved, streamed or
played here. Playback needs a backend that this build does not include, so
`playback_blockers()` lists what is missing instead of pretending to play.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
from collections import deque

MAX_QUEUE = 100
MAX_TITLE = 200


class MusicQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def add(self, title: str) -> None:
        clean = " ".join(title.split())[:MAX_TITLE]
        if not clean:
            raise ValueError("empty title")
        if len(self._items) >= MAX_QUEUE:
            raise OverflowError("queue full")
        self._items.append(clean)

    def skip(self) -> str | None:
        return self._items.popleft() if self._items else None

    def clear(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def items(self) -> list[str]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


def playback_blockers() -> list[str]:
    blockers: list[str] = []
    if not shutil.which("ffmpeg"):
        blockers.append("ffmpeg is not on PATH")
    if importlib.util.find_spec("nacl") is None:
        blockers.append("PyNaCl is not installed (needed for voice)")
    if not os.getenv("MUSIC_STREAM_PROVIDER"):
        blockers.append("no stream provider configured (MUSIC_STREAM_PROVIDER)")
    blockers.append("no playback backend is included in this build")
    return blockers
