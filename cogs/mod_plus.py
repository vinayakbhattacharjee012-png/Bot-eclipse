"""Extra moderation: softban, tempban, nickname and role changes, a per-member case log,
and automatic escalation after a set number of warnings."""
from __future__ import annotations

import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils import scheduler
from utils.storage import store

MAX_CASES = 1000
ESCALATION_TIMEOUT_MINUTES = 60


def _sec(guild_id: int) -> dict:
    sec = store.guild(guild_id)
    sec.setdefault("cases", [])
    sec.setdefault("escalation", {"timeout_at": 0, "ban_at": 0})
    return sec


def log_case(guild_id: int, kind: str, user_id: int, mod_id: int | None, reason: str) -> int:
    """Append a moderation case and return its number. Caller saves the store."""
    cases = _sec(guild_id)["cases"]
    number = (cases[-1]["number"] + 1) if cases else 1
    cases.append({"number": number, "kind": kind, "user_id": user_id, "mod_id": mod_id, "reason": reason[:300], "ts": time.time()})
    del cases[:-MAX_CASES]
    return number


async def escalate(guild: discord.Guild, member: discord.Member, warn_count: int, moderator: discord.abc.User) -> str | None:
    """Apply the configured warning thresholds. Returns a note for the moderator, or None."""
    esc = _sec(guild.id)["escalation"]
    if esc["ban_at"] and warn_count >= esc["ban_at"]:
        try:
            await guild.ban(member, reason=f"Automatic: {warn_count} warnings", delete_message_days=0)
        except discord.HTTPException:
            return "Auto-ban failed (check my permissions)."
        log_case(guild.id, "auto-ban", member.id, None, f"{warn_count} warnings")
        await store.save()
        return f"Auto-banned at {warn_count} warnings."
    if esc["timeout_at"] and warn_count >= esc["timeout_at"]:
        try:
            await member.timeout(timedelta(minutes=ESCALATION_TIMEOUT_MINUTES), reason=f"Automatic: {warn_count} warnings")
        except discord.HTTPException:
            return "Auto-timeout failed (check my permissions)."
        log_case(guild.id, "auto-timeout", member.id, None, f"{warn_count} warnings")
        await store.save()
        return f"Auto-timed out for {ESCALATION_TIMEOUT_MINUTES} minutes at {warn_count} warnings."
    return None


@scheduler.handler("unban")
async def _expire_tempban(bot, guild_id: int, payload: dict) -> None:
    guild = bot.get_guild(guild_id)
    if guild is None:
        return
    try:
        await guild.unban(discord.Object(id=payload["user_id"]), reason="Tempban expired")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return
    log_case(guild_id, "unban (tempban expired)", payload["user_id"], None, "Tempban expired")
    await store.save()


def _can_act_on(actor: discord.Member, target: discord.Member, me: discord.Member) -> str | None:
    if target.id == actor.id:
        return "You can't do that to yourself."
    if target.top_role >= actor.top_role and actor.id != actor.guild.owner_id:
        return "That member's top role is equal to or above yours."
    if target.top_role >= me.top_role:
        return "That member's top role is equal to or above mine, so I can't act on them."
    return None


class ModPlus(commands.Cog):
    mod = app_commands.Group(name="mod", description="Softban, tempban, nickname, roles, case log and escalation", guild_only=True)

    @mod.command(description="Ban and immediately unban to delete recent messages.")
    @app_commands.describe(member="Who to softban", reason="Why", delete_days="Days of their messages to delete (0 to 7)")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def softban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given", delete_days: app_commands.Range[int, 0, 7] = 1) -> None:
        problem = _can_act_on(interaction.user, member, interaction.guild.me)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await interaction.guild.ban(member, reason=f"Softban by {interaction.user}: {reason}", delete_message_days=delete_days)
            await interaction.guild.unban(member, reason="Softban complete")
        except discord.HTTPException:
            await interaction.response.send_message("I couldn't softban that member.", ephemeral=True)
            return
        log_case(interaction.guild_id, "softban", member.id, interaction.user.id, reason)
        await store.save()
        await interaction.response.send_message(f"Softbanned **{member}**. They can rejoin. Reason: {reason}")

    @mod.command(description="Ban for a set time. The ban lifts automatically.")
    @app_commands.describe(member="Who to tempban", minutes="How long, in minutes (1 to 43200)", reason="Why")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 43200], reason: str = "No reason given") -> None:
        problem = _can_act_on(interaction.user, member, interaction.guild.me)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await interaction.guild.ban(member, reason=f"Tempban {minutes}m by {interaction.user}: {reason}", delete_message_days=0)
        except discord.HTTPException:
            await interaction.response.send_message("I couldn't ban that member.", ephemeral=True)
            return
        scheduler.add(interaction.guild_id, "unban", time.time() + minutes * 60, {"user_id": member.id})
        log_case(interaction.guild_id, "tempban", member.id, interaction.user.id, f"{minutes}m: {reason}")
        await store.save()
        await interaction.response.send_message(f"Tempbanned **{member}** for {minutes} minute(s). Reason: {reason}")

    @mod.command(description="Change a member's nickname. Leave empty to reset it.")
    @app_commands.describe(member="Who to rename", name="New nickname (optional)")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    @app_commands.checks.bot_has_permissions(manage_nicknames=True)
    async def nick(self, interaction: discord.Interaction, member: discord.Member, name: app_commands.Range[str, 1, 32] | None = None) -> None:
        problem = _can_act_on(interaction.user, member, interaction.guild.me)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await member.edit(nick=name, reason=f"Nickname changed by {interaction.user}")
        except discord.HTTPException:
            await interaction.response.send_message("I couldn't change that nickname.", ephemeral=True)
            return
        await interaction.response.send_message(f"Nickname for **{member}** is now {name or 'reset'}.")

    @mod.command(name="role_add", description="Give a member a role.")
    @app_commands.describe(member="Who gets the role", role="The role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("That role is above mine, so I can't give it.", ephemeral=True)
            return
        await member.add_roles(role, reason=f"Added by {interaction.user}")
        await interaction.response.send_message(f"Gave {role.mention} to **{member.display_name}**.", allowed_mentions=discord.AllowedMentions.none())

    @mod.command(name="role_remove", description="Take a role from a member.")
    @app_commands.describe(member="Who loses the role", role="The role")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role) -> None:
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("That role is above mine, so I can't take it.", ephemeral=True)
            return
        await member.remove_roles(role, reason=f"Removed by {interaction.user}")
        await interaction.response.send_message(f"Took {role.mention} from **{member.display_name}**.", allowed_mentions=discord.AllowedMentions.none())

    @mod.command(description="Show recent moderation cases for a member.")
    @app_commands.describe(member="Whose cases to show")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def cases(self, interaction: discord.Interaction, member: discord.Member) -> None:
        mine = [c for c in _sec(interaction.guild_id)["cases"] if c["user_id"] == member.id][-10:]
        if not mine:
            await interaction.response.send_message(f"No cases for **{member.display_name}**.", ephemeral=True)
            return
        lines = [f"`#{c['number']}` {c['kind']} · <t:{int(c['ts'])}:R> · {c['reason']}" for c in mine]
        await interaction.response.send_message(embed=discord.Embed(title=f"Cases for {member.display_name}", description="\n".join(lines), color=discord.Color.orange()), ephemeral=True)

    @mod.command(description="Automatic action after a number of warnings (0 = off).")
    @app_commands.describe(timeout_at="Warnings before a 60-minute timeout", ban_at="Warnings before a ban")
    @app_commands.checks.has_permissions(administrator=True)
    async def escalation(self, interaction: discord.Interaction, timeout_at: app_commands.Range[int, 0, 50], ban_at: app_commands.Range[int, 0, 50]) -> None:
        if timeout_at and ban_at and ban_at <= timeout_at:
            await interaction.response.send_message("The ban threshold must be higher than the timeout threshold.", ephemeral=True)
            return
        _sec(interaction.guild_id)["escalation"] = {"timeout_at": timeout_at, "ban_at": ban_at}
        await store.save()
        await interaction.response.send_message(f"Timeout at {timeout_at or 'never'} warnings, ban at {ban_at or 'never'}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModPlus())
