"""Persisted one-shot jobs: reminders, tempban expiry, giveaway ends.

Jobs live in each server's data, so they survive restarts. One loop checks
for due jobs every 15 seconds. A job is removed before its handler runs, so a
crash mid-handler drops that job rather than repeating it.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from utils.storage import store

log = logging.getLogger("scheduler")
TICK_SECONDS = 15

Handler = Callable[[Any, int, dict], Awaitable[None]]
_handlers: dict[str, Handler] = {}
_task: asyncio.Task | None = None


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn
    return register


def add(guild_id: int, kind: str, due: float, payload: dict) -> str:
    """Queue a job. Caller must `await store.save()`."""
    job_id = uuid.uuid4().hex[:8]
    store.guild(guild_id).setdefault("jobs", []).append({"id": job_id, "kind": kind, "due": due, "payload": payload})
    return job_id


async def run_due(bot: Any, now: float) -> int:
    ran = 0
    for gid in store.guild_ids():
        g = store.guild(int(gid))
        jobs = g.get("jobs") or []
        due = [j for j in jobs if j["due"] <= now]
        if not due:
            continue
        g["jobs"] = [j for j in jobs if j["due"] > now]
        await store.save()
        for job in due:
            fn = _handlers.get(job["kind"])
            if fn is None:
                log.warning("No handler for job kind %r; dropped", job["kind"])
                continue
            try:
                await fn(bot, int(gid), job["payload"])
                ran += 1
            except Exception:
                log.exception("Job %s (%s) failed", job["id"], job["kind"])
    return ran


async def _loop(bot: Any) -> None:
    while True:
        try:
            await run_due(bot, time.time())
        except Exception:
            log.exception("Scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


def start(bot: Any) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(bot))
