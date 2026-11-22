"""AniCatch: creatures spawn in busy channels. Catch them, build a dex, battle and trade."""
from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import features, registry
from utils.confirm import ConfirmView
from utils.storage import store


def _sec(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("anicatch", {})
    sec.setdefault("dex", {})
    sec.setdefault("misses", {})
    return sec


async def _owned_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    dex = _sec(interaction.guild_id)["dex"].get(str(interaction.user.id), {})
    cur = current.lower()
    return [
        app_commands.Choice(name=f"{name} (x{count})", value=name)
        for name, count in dex.items()
        if count > 0 and cur in name.lower()
    ][:25]


class AniCatch(commands.Cog):
    anicatch = app_commands.Group(name="anicatch", description="Catch creatures, build your dex, battle and trade", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._messages_since_spawn: dict[int, int] = {}
        self._last_spawn: dict[int, float] = {}
        self._active: dict[int, tuple[str, float]] = {}  # channel id -> (creature, expires at)

    def _live_spawn(self, channel_id: int, now: float) -> str | None:
        spawn = self._active.get(channel_id)
        if spawn is None:
            return None
        name, expires = spawn
        if now >= expires:
            del self._active[channel_id]
            return None
        return name

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not features.enabled(message.guild.id, "anicatch"):
            return
        eng = registry.get("anicatch")
        now = time.time()
        cid = message.channel.id
        self._messages_since_spawn[cid] = self._messages_since_spawn.get(cid, 0) + 1
        if (
            self._live_spawn(cid, now) is not None
            or self._messages_since_spawn[cid] < eng.SPAWN_EVERY_MESSAGES
            or now - self._last_spawn.get(cid, 0) < eng.SPAWN_MIN_GAP
        ):
            return
        name = eng.roll_spawn(random)
        self._active[cid] = (name, now + eng.SPAWN_TTL)
        self._messages_since_spawn[cid] = 0
        self._last_spawn[cid] = now
        try:
            await message.channel.send(
                f"A wild **{name}** ({eng.rarity_of(name)}) appeared! Use `/anicatch catch` within {eng.SPAWN_TTL} seconds."
            )
        except discord.HTTPException:
            pass

    @anicatch.command(description="Try to catch the creature that is in this channel right now.")
    async def catch(self, interaction: discord.Interaction) -> None:
        eng = registry.get("anicatch")
        name = self._live_spawn(interaction.channel_id, time.time())
        if name is None:
            await interaction.response.send_message("Nothing to catch here right now. Creatures appear as the chat gets busy.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        uid = str(interaction.user.id)
        misses = sec["misses"].get(uid, 0)
        if eng.attempt_catch(random, name, misses):
            dex = sec["dex"].setdefault(uid, {})
            dex[name] = dex.get(name, 0) + 1
            sec["misses"][uid] = 0
            self._active.pop(interaction.channel_id, None)
            await store.save()
            new = " New species!" if dex[name] == 1 else ""
            await interaction.response.send_message(f"🎣 You caught **{name}**!{new}")
        else:
            sec["misses"][uid] = misses + 1
            await store.save()
            await interaction.response.send_message(f"💨 **{name}** got away.", ephemeral=True)

    @anicatch.command(description="See which creatures you (or someone else) have caught.")
    @app_commands.describe(member="Whose dex to view")
    async def dex(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        eng = registry.get("anicatch")
        member = member or interaction.user
        counts = _sec(interaction.guild_id)["dex"].get(str(member.id), {})
        lines = []
        for name, rarity, _power in eng.CREATURES:
            if counts.get(name, 0) > 0:
                lines.append(f"✅ **{name}** ({rarity}) ×{counts[name]}")
            else:
                lines.append(f"❔ ??? ({rarity})")
        caught = sum(1 for n, *_ in eng.CREATURES if counts.get(n, 0) > 0)
        embed = discord.Embed(title=f"{member.display_name}'s dex · {caught}/{len(eng.CREATURES)}", description="\n".join(lines), color=discord.Color.teal())
        await interaction.response.send_message(embed=embed)

    @anicatch.command(description="Battle another member with your best three creatures.")
    @app_commands.describe(member="Who to battle")
    async def battle(self, interaction: discord.Interaction, member: discord.Member) -> None:
        eng = registry.get("anicatch")
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("Pick someone else to battle.", ephemeral=True)
            return
        dex = _sec(interaction.guild_id)["dex"]
        mine = eng.battle_power(dex.get(str(interaction.user.id), {}), random)
        theirs = eng.battle_power(dex.get(str(member.id), {}), random)
        if mine == 0 and theirs == 0:
            text = "Neither of you has creatures yet."
        elif mine == theirs:
            text = f"Draw at {mine} power each."
        else:
            winner = interaction.user if mine > theirs else member
            text = f"**{winner.display_name}** wins! ({mine} vs {theirs} power)"
        await interaction.response.send_message(f"⚔️ {interaction.user.display_name} vs {member.display_name}\n{text}")

    @anicatch.command(description="Offer one of your creatures to someone. They must accept.")
    @app_commands.describe(member="Who to trade with", creature="The creature to give")
    @app_commands.autocomplete(creature=_owned_choices)
    async def trade(self, interaction: discord.Interaction, member: discord.Member, creature: str) -> None:
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("Pick someone else to trade with.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        if sec["dex"].get(str(interaction.user.id), {}).get(creature, 0) < 1:
            await interaction.response.send_message("You don't have that creature.", ephemeral=True)
            return
        view = ConfirmView(owner_id=member.id, timeout=120)
        await interaction.response.send_message(
            f"{member.mention}, **{interaction.user.display_name}** offers you **{creature}**. Accept?",
            view=view,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        await view.wait()
        if view.value is None:
            await interaction.followup.send("The trade expired.")
            return
        if not view.value:
            await interaction.followup.send("The trade was declined.")
            return
        giver = sec["dex"].get(str(interaction.user.id), {})
        if giver.get(creature, 0) < 1:
            await interaction.followup.send("The creature is no longer available.")
            return
        giver[creature] -= 1
        receiver = sec["dex"].setdefault(str(member.id), {})
        receiver[creature] = receiver.get(creature, 0) + 1
        await store.save()
        await interaction.followup.send(f"Trade done. {member.mention} now has **{creature}**.", allowed_mentions=discord.AllowedMentions(users=[member]))

    @anicatch.command(description="Members with the most different creatures caught.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        dex_all = _sec(interaction.guild_id)["dex"]
        rows = sorted(((uid, sum(1 for c in d.values() if c > 0)) for uid, d in dex_all.items()), key=lambda r: r[1], reverse=True)
        rows = [r for r in rows if r[1] > 0][:10]
        if not rows:
            await interaction.response.send_message("Nobody has caught anything yet.", ephemeral=True)
            return
        lines = []
        for i, (uid, species) in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"`#{i}` **{name}** — {species} species")
        await interaction.response.send_message(embed=discord.Embed(title="AniCatch leaderboard", description="\n".join(lines), color=discord.Color.teal()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AniCatch(bot))
