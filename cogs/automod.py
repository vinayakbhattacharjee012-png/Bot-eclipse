"""Automod: deletes messages that break a rule (invites, links, mass mentions, caps, zalgo,
emoji spam, blocked words, duplicates), records a strike, and escalates on strike counts."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils import audit, automod_rules, features
from utils.storage import store

TIMEOUT_MINUTES = 10
RULE_NAMES = tuple(automod_rules.DEFAULT_RULES)


def _cfg(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("automod", {})
    sec.setdefault("rules", {})
    sec.setdefault("words", [])
    sec.setdefault("domains", [])
    sec.setdefault("allowed_invites", [])
    sec.setdefault("strikes", {})
    sec.setdefault("strikes_timeout", 3)
    sec.setdefault("strikes_ban", 6)
    return sec


class Automod(commands.Cog):
    automod = app_commands.Group(name="automod", description="Auto-moderation rules, filters and strikes", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._dup: dict[tuple[int, int], deque] = defaultdict(deque)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if not features.enabled(message.guild.id, "automod"):
            return
        member = message.author
        if isinstance(member, discord.Member) and member.guild_permissions.manage_messages:
            return
        sec = _cfg(message.guild.id)
        cfg = {
            "rules": sec["rules"], "words": sec["words"], "domains": sec["domains"],
            "allowed_invites": sec["allowed_invites"],
        }
        hits = automod_rules.check_message(message.content, cfg, self._dup[(message.guild.id, member.id)], time.time())
        if not hits:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        uid = str(member.id)
        strikes = sec["strikes"].get(uid, 0) + 1
        sec["strikes"][uid] = strikes
        await store.save()
        reasons = ", ".join(hits)
        try:
            await message.channel.send(
                f"{member.mention}, that message was removed ({reasons}). Strike {strikes}.",
                delete_after=10, allowed_mentions=discord.AllowedMentions(users=[member]),
            )
        except discord.HTTPException:
            pass

        action = "strike"
        if sec["strikes_ban"] and strikes >= sec["strikes_ban"]:
            action = "ban"
            try:
                await message.guild.ban(member, reason=f"Automod: {strikes} strikes", delete_message_days=0)
            except discord.HTTPException:
                action = "ban failed (check my permissions)"
        elif sec["strikes_timeout"] and strikes >= sec["strikes_timeout"]:
            action = f"timeout {TIMEOUT_MINUTES}m"
            try:
                await member.timeout(timedelta(minutes=TIMEOUT_MINUTES), reason=f"Automod: {strikes} strikes")
            except discord.HTTPException:
                action = "timeout failed (check my permissions)"
        await audit.record(
            message.guild, "automod",
            f"{member} ({member.id}) broke: {reasons}. Strike {strikes}. Action: {action}.",
            actor_id=member.id,
        )

    # ---------- configuration ----------

    @automod.command(description="Show the current automod settings.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction) -> None:
        sec = _cfg(interaction.guild_id)
        rules = {**automod_rules.DEFAULT_RULES, **sec["rules"]}
        lines = [f"{'on' if rules[r] else 'off'} · `{r}`" for r in RULE_NAMES]
        lines.append(f"Blocked words: {len(sec['words'])} · blocked domains: {len(sec['domains'])}")
        lines.append(f"Strikes → timeout at {sec['strikes_timeout'] or 'never'}, ban at {sec['strikes_ban'] or 'never'}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @automod.command(description="Turn one rule on or off.")
    @app_commands.describe(rule="The rule to change", enabled="On or off")
    @app_commands.choices(rule=[app_commands.Choice(name=r, value=r) for r in RULE_NAMES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rule(self, interaction: discord.Interaction, rule: app_commands.Choice[str], enabled: bool) -> None:
        _cfg(interaction.guild_id)["rules"][rule.value] = enabled
        await store.save()
        await interaction.response.send_message(f"`{rule.value}` is now **{'on' if enabled else 'off'}**.", ephemeral=True)

    @automod.command(name="word_add", description="Add a blocked word (whole words only, any case).")
    @app_commands.describe(word="The word or phrase to block")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def word_add(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 50]) -> None:
        words = _cfg(interaction.guild_id)["words"]
        clean = word.strip().lower()
        if clean and clean not in words:
            words.append(clean)
        await store.save()
        await interaction.response.send_message(f"Blocked word list now has {len(words)} entries.", ephemeral=True)

    @automod.command(name="word_remove", description="Remove a blocked word.")
    @app_commands.describe(word="The word to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def word_remove(self, interaction: discord.Interaction, word: app_commands.Range[str, 1, 50]) -> None:
        words = _cfg(interaction.guild_id)["words"]
        if word.strip().lower() in words:
            words.remove(word.strip().lower())
            await store.save()
            await interaction.response.send_message("Removed.", ephemeral=True)
        else:
            await interaction.response.send_message("That word isn't on the list.", ephemeral=True)

    @automod.command(name="domain_add", description="Block links to a domain (and its subdomains). Needs the links rule on.")
    @app_commands.describe(domain="For example bad-site.example")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def domain_add(self, interaction: discord.Interaction, domain: app_commands.Range[str, 3, 120]) -> None:
        domains = _cfg(interaction.guild_id)["domains"]
        clean = domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if clean and clean not in domains:
            domains.append(clean)
        await store.save()
        await interaction.response.send_message(f"`{clean}` is blocked. Turn on the `links` rule to enforce it.", ephemeral=True)

    @automod.command(name="strikes", description="Set when strikes cause a timeout or a ban (0 = never).")
    @app_commands.describe(timeout_at="Strikes before a 10-minute timeout", ban_at="Strikes before a ban")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def strikes(
        self, interaction: discord.Interaction,
        timeout_at: app_commands.Range[int, 0, 50], ban_at: app_commands.Range[int, 0, 50],
    ) -> None:
        sec = _cfg(interaction.guild_id)
        if timeout_at and ban_at and ban_at <= timeout_at:
            await interaction.response.send_message("The ban threshold must be higher than the timeout threshold.", ephemeral=True)
            return
        sec["strikes_timeout"], sec["strikes_ban"] = timeout_at, ban_at
        await store.save()
        await interaction.response.send_message(f"Timeout at {timeout_at or 'never'} strikes, ban at {ban_at or 'never'}.", ephemeral=True)

    @automod.command(name="clear_strikes", description="Reset one member's strikes.")
    @app_commands.describe(member="Whose strikes to clear")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear_strikes(self, interaction: discord.Interaction, member: discord.Member) -> None:
        _cfg(interaction.guild_id)["strikes"].pop(str(member.id), None)
        await store.save()
        await interaction.response.send_message(f"Cleared strikes for **{member.display_name}**.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Automod(bot))
