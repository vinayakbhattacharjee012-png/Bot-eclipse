"""XP / leveling system: gain XP from chatting (with a cooldown so you can't
spam your way up), level-up announcements, a leaderboard, and optional
roles awarded automatically at specific levels."""
from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import features
from utils.storage import store

XP_MIN, XP_MAX = 15, 25
XP_COOLDOWN_SECONDS = 60


def xp_for_level(level: int) -> int:
    """Total XP required to REACH this level. A standard-ish curve that
    gets gradually harder, similar to common leveling bots."""
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cooldowns: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not features.enabled(message.guild.id, "leveling"):
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self._cooldowns.get(key, 0) < XP_COOLDOWN_SECONDS:
            return
        self._cooldowns[key] = now

        g = store.guild(message.guild.id)
        user_data = g["levels"].setdefault(str(message.author.id), {"xp": 0, "level": 0})
        user_data["xp"] += random.randint(XP_MIN, XP_MAX)
        new_level = level_from_xp(user_data["xp"])
        leveled_up = new_level > user_data["level"]
        user_data["level"] = new_level
        await store.save()

        if leveled_up:
            await self._announce_level_up(message, new_level)
            await self._apply_level_roles(message.author, g, new_level)

    async def _announce_level_up(self, message: discord.Message, new_level: int) -> None:
        g = store.guild(message.guild.id)
        channel_id = g["config"].get("level_up_channel_id")
        channel = message.guild.get_channel(channel_id) if channel_id else message.channel
        if channel is None:
            channel = message.channel
        try:
            await channel.send(f"🎉 {message.author.mention} just reached **level {new_level}**!")
        except discord.HTTPException:
            pass

    async def _apply_level_roles(self, member: discord.Member, g: dict, new_level: int) -> None:
        role_id = g["level_roles"].get(str(new_level))
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role, reason=f"Reached level {new_level}")
            except discord.Forbidden:
                pass

    @app_commands.command(description="Check your (or someone else's) level and XP.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        g = store.guild(interaction.guild_id)
        data = g["levels"].get(str(member.id), {"xp": 0, "level": 0})
        xp, level = data["xp"], data["level"]
        next_level_xp = xp_for_level(level + 1)
        this_level_xp = xp_for_level(level)
        progress = xp - this_level_xp
        needed = next_level_xp - this_level_xp
        bar_len = 20
        filled = int(bar_len * progress / needed) if needed else bar_len
        bar = "█" * filled + "░" * (bar_len - filled)

        embed = discord.Embed(title=f"{member.display_name}'s rank", color=member.color or discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Total XP", value=str(xp), inline=True)
        embed.add_field(name="Progress to next level", value=f"`{bar}` {progress}/{needed} XP", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="See the server's top members by level/XP.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        g = store.guild(interaction.guild_id)
        rows = sorted(g["levels"].items(), key=lambda kv: kv[1]["xp"], reverse=True)[:10]
        if not rows:
            await interaction.response.send_message("No one has earned any XP yet.", ephemeral=True)
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(rows):
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else f"User {user_id}"
            prefix = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{prefix} **{name}** — Level {data['level']} ({data['xp']} XP)")

        embed = discord.Embed(title=f"🏆 {interaction.guild.name} Leaderboard", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Set the channel level-up announcements get posted in.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlevelchannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        g = store.guild(interaction.guild_id)
        g["config"]["level_up_channel_id"] = channel.id
        await store.save()
        await interaction.response.send_message(f"Level-up announcements will go to {channel.mention}.", ephemeral=True)

    @app_commands.command(description="Automatically give a role when a member reaches a level.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlevelrole(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 1000], role: discord.Role) -> None:
        g = store.guild(interaction.guild_id)
        g["level_roles"][str(level)] = role.id
        await store.save()
        await interaction.response.send_message(f"Members who reach level {level} will now get {role.mention}.", ephemeral=True)

    @app_commands.command(description="Remove a level-up role reward.")
    @app_commands.checks.has_permissions(administrator=True)
    async def removelevelrole(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 1000]) -> None:
        g = store.guild(interaction.guild_id)
        had = g["level_roles"].pop(str(level), None)
        await store.save()
        if had:
            await interaction.response.send_message(f"Removed the role reward for level {level}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Level {level} had no role reward set.", ephemeral=True)

    @app_commands.command(description="Manually add or remove XP from a member.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setxp(self, interaction: discord.Interaction, member: discord.Member, xp: app_commands.Range[int, 0, 10_000_000]) -> None:
        g = store.guild(interaction.guild_id)
        data = g["levels"].setdefault(str(member.id), {"xp": 0, "level": 0})
        data["xp"] = xp
        data["level"] = level_from_xp(xp)
        await store.save()
        await interaction.response.send_message(f"Set **{member}**'s XP to {xp} (level {data['level']}).", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leveling(bot))
