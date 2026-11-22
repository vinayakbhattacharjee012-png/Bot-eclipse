"""Giveaways: members react with 🎉 to enter. When the timer ends, winners are picked at random
from the entries (bots excluded). The end time is persisted, so it survives restarts."""
from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import scheduler
from utils.storage import store

ENTRY_EMOJI = "🎉"


def pick_winners(entrant_ids: list[int], count: int, rng: random.Random) -> list[int]:
    unique = list(dict.fromkeys(entrant_ids))
    return rng.sample(unique, min(count, len(unique)))


@scheduler.handler("giveaway_end")
async def _end_giveaway(bot, guild_id: int, payload: dict) -> None:
    channel = bot.get_channel(payload["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(payload["message_id"])
    except discord.HTTPException:
        return
    reaction = next((r for r in message.reactions if str(r.emoji) == ENTRY_EMOJI), None)
    entrants = []
    if reaction is not None:
        entrants = [u.id async for u in reaction.users(limit=1000) if not u.bot]
    winners = pick_winners(entrants, payload["winners"], random.Random())
    if winners:
        text = f"🎉 Giveaway ended. **{payload['prize']}** goes to " + ", ".join(f"<@{w}>" for w in winners) + "!"
    else:
        text = f"🎉 Giveaway ended for **{payload['prize']}**, but nobody entered."
    await channel.send(text, allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))


class Giveaways(commands.Cog):
    giveaway = app_commands.Group(name="giveaway", description="Run a giveaway with 🎉 entries", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        scheduler.start(self.bot)

    @giveaway.command(description="Start a giveaway. Members react with 🎉 to enter.")
    @app_commands.describe(prize="What is being given away", minutes="How long it runs (1 to 10080)", winners="How many winners (1 to 10)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(add_reactions=True, send_messages=True)
    async def start(self, interaction: discord.Interaction, prize: app_commands.Range[str, 1, 200], minutes: app_commands.Range[int, 1, 10080], winners: app_commands.Range[int, 1, 10] = 1) -> None:
        ends = time.time() + minutes * 60
        embed = discord.Embed(
            title=f"🎉 Giveaway: {prize}",
            description=f"React with {ENTRY_EMOJI} to enter.\nWinners: {winners}\nEnds <t:{int(ends)}:R>",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction(ENTRY_EMOJI)
        scheduler.add(interaction.guild_id, "giveaway_end", ends, {
            "channel_id": interaction.channel_id, "message_id": message.id, "prize": prize, "winners": winners,
        })
        await store.save()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))
