"""AFK tracking: /afk sets your status, it clears automatically next time
you post, and anyone who @-mentions you while you're away gets told."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import features
from utils.storage import store


class AFK(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(description="Mark yourself as AFK with an optional reason.")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        g = store.guild(interaction.guild_id)
        g["afk"][str(interaction.user.id)] = {"reason": reason, "timestamp": time.time()}
        await store.save()

        nickname_note = ""
        if isinstance(interaction.user, discord.Member) and interaction.guild.me.guild_permissions.manage_nicknames:
            try:
                if not interaction.user.display_name.startswith("[AFK] "):
                    await interaction.user.edit(nick=f"[AFK] {interaction.user.display_name}"[:32])
            except discord.Forbidden:
                nickname_note = " (couldn't update your nickname — I may be missing permission)"

        await interaction.response.send_message(f"💤 You're now AFK: {reason}{nickname_note}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not features.enabled(message.guild.id, "afk"):
            return
        g = store.guild(message.guild.id)
        afk_map = g["afk"]

        # Welcome back if the author was AFK.
        if str(message.author.id) in afk_map:
            del afk_map[str(message.author.id)]
            await store.save()
            if isinstance(message.author, discord.Member) and message.author.display_name.startswith("[AFK] "):
                try:
                    await message.author.edit(nick=message.author.display_name[len("[AFK] "):] or None)
                except discord.Forbidden:
                    pass
            try:
                await message.channel.send(f"👋 Welcome back, {message.author.mention}! I've removed your AFK status.", delete_after=8)
            except discord.HTTPException:
                pass

        # Tell the author if they mentioned someone who's AFK.
        if message.mentions:
            notes = []
            for user in message.mentions:
                entry = afk_map.get(str(user.id))
                if entry:
                    mins = int((time.time() - entry["timestamp"]) / 60)
                    notes.append(f"**{user.display_name}** is AFK ({entry['reason']}) — {mins}m ago")
            if notes:
                try:
                    await message.channel.send("\n".join(notes), delete_after=15)
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AFK(bot))
