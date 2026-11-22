"""Security and automod audit trail. Each server keeps its last 500 entries, and
each entry is posted to the mod-log channel when one is set."""
from __future__ import annotations

import time

import discord

from utils.storage import store

MAX_ENTRIES = 500


async def record(guild: discord.Guild, action: str, detail: str, actor_id: int | None = None) -> None:
    g = store.guild(guild.id)
    entries = g.setdefault("audit", [])
    entries.append({"ts": time.time(), "action": action, "detail": detail[:500], "actor_id": actor_id})
    del entries[:-MAX_ENTRIES]
    await store.save()

    channel_id = g["config"].get("log_channel_id")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is not None:
        embed = discord.Embed(
            title=f"Audit: {action}", description=detail[:4000],
            color=discord.Color.dark_red(), timestamp=discord.utils.utcnow(),
        )
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
