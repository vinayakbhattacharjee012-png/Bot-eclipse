"""Lightweight anti-raid: watches join rate and new-account age, and can
auto-kick very-new accounts that join during a detected raid wave."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._recent_joins: dict[int, deque[float]] = defaultdict(deque)
        self._raid_mode_until: dict[int, float] = {}

    async def _log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        cfg = store.guild(guild.id)["config"]
        channel_id = cfg.get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @app_commands.command(description="Configure the automatic anti-raid (mass-join) detector.")
    @app_commands.describe(
        enabled="Turn raid detection on or off",
        join_threshold="How many joins within the window count as a raid",
        window_seconds="The time window, in seconds",
        min_account_age_hours="During a raid, auto-kick new joins with an account younger than this (0 = don't auto-kick)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def antiraid(
        self, interaction: discord.Interaction,
        enabled: bool | None = None,
        join_threshold: app_commands.Range[int, 2, 100] | None = None,
        window_seconds: app_commands.Range[int, 2, 300] | None = None,
        min_account_age_hours: app_commands.Range[int, 0, 720] | None = None,
    ) -> None:
        cfg = store.guild(interaction.guild_id)["config"]
        if enabled is not None:
            cfg["antiraid_enabled"] = enabled
        if join_threshold is not None:
            cfg["antiraid_join_threshold"] = join_threshold
        if window_seconds is not None:
            cfg["antiraid_window_seconds"] = window_seconds
        if min_account_age_hours is not None:
            cfg["antiraid_min_account_age_hours"] = min_account_age_hours
        await store.save()
        await interaction.response.send_message(
            f"Anti-raid: **{'on' if cfg['antiraid_enabled'] else 'off'}** — "
            f"{cfg['antiraid_join_threshold']} joins / {cfg['antiraid_window_seconds']}s triggers raid mode, "
            f"auto-kick accounts younger than {cfg['antiraid_min_account_age_hours']}h while active "
            f"({'disabled' if cfg['antiraid_min_account_age_hours'] == 0 else 'enabled'}).",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        cfg = store.guild(guild.id)["config"]
        if not cfg.get("antiraid_enabled", True):
            return

        now = time.monotonic()
        window = cfg.get("antiraid_window_seconds", 10)
        dq = self._recent_joins[guild.id]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()

        threshold = cfg.get("antiraid_join_threshold", 6)
        in_raid_mode = len(dq) >= threshold

        if in_raid_mode and self._raid_mode_until.get(guild.id, 0) < now:
            self._raid_mode_until[guild.id] = now + 60  # raid mode lasts 60s after last trip
            await self._log(guild, discord.Embed(
                title="🚨 Possible raid detected",
                description=f"{len(dq)} members joined within {window}s. Raid mode is active for new joins for the next 60s.",
                color=discord.Color.red(),
            ))
        elif in_raid_mode:
            self._raid_mode_until[guild.id] = now + 60

        if now < self._raid_mode_until.get(guild.id, 0):
            min_age_hours = cfg.get("antiraid_min_account_age_hours", 24)
            if min_age_hours > 0:
                age = datetime.now(timezone.utc) - member.created_at
                if age.total_seconds() < min_age_hours * 3600:
                    try:
                        await member.kick(reason="Anti-raid: new account joined during a detected raid wave")
                        await self._log(guild, discord.Embed(
                            title="Anti-raid auto-kick",
                            description=f"Kicked **{member}** ({member.id}) — account is only {age.days}d old.",
                            color=discord.Color.dark_red(),
                        ))
                    except discord.Forbidden:
                        await self._log(guild, discord.Embed(
                            title="Anti-raid: couldn't kick",
                            description=f"Tried to kick **{member}** but I'm missing permission.",
                            color=discord.Color.dark_red(),
                        ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiRaid(bot))
