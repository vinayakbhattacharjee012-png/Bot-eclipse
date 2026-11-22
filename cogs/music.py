"""Music: a per-server request queue and an honest status report.

Queueing works. Playback does not: this build has no audio backend, so /music status lists
what is missing (see utils/music_queue.py). Nothing is streamed or faked."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import registry
from utils.music_queue import MAX_QUEUE, MusicQueue, playback_blockers

_queues: dict[int, MusicQueue] = {}


def _queue(guild_id: int) -> MusicQueue:
    if guild_id not in _queues:
        _queues[guild_id] = MusicQueue()
    return _queues[guild_id]


class Music(commands.Cog):
    music = app_commands.Group(name="music", description="Request queue and playback status", guild_only=True)

    @music.command(description="Show whether playback can work on this bot.")
    async def status(self, interaction: discord.Interaction) -> None:
        registry.get("music")
        blockers = playback_blockers()
        lines = ["**Queue:** works (requests are stored, nothing is played yet)", "**Playback:** unavailable", "Missing:"]
        lines += [f"• {b}" for b in blockers]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @music.command(description="Add a track to the queue by name or link.")
    @app_commands.describe(track="Song name or link")
    async def add(self, interaction: discord.Interaction, track: app_commands.Range[str, 1, 200]) -> None:
        try:
            _queue(interaction.guild_id).add(track)
        except OverflowError:
            await interaction.response.send_message(f"The queue is full ({MAX_QUEUE} tracks).", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("That track name is empty.", ephemeral=True)
            return
        await interaction.response.send_message(f"Queued: **{track.strip()}** (position {len(_queue(interaction.guild_id))}).")

    @music.command(description="Show the queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        items = _queue(interaction.guild_id).items()
        if not items:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        lines = [f"`{i}.` {t}" for i, t in enumerate(items[:20], start=1)]
        if len(items) > 20:
            lines.append(f"…and {len(items) - 20} more")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @music.command(description="Remove the first track from the queue.")
    async def skip(self, interaction: discord.Interaction) -> None:
        removed = _queue(interaction.guild_id).skip()
        if removed is None:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Removed **{removed}** from the queue. (Nothing was playing.)")

    @music.command(description="Empty the queue.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear(self, interaction: discord.Interaction) -> None:
        count = _queue(interaction.guild_id).clear()
        await interaction.response.send_message(f"Cleared {count} track(s).", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music())
