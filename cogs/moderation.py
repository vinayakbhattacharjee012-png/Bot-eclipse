"""Moderation commands: kick, ban, timeout, warnings, purge, lock/unlock,
and a lightweight automatic anti-spam filter."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store


def _mod_only():
    return app_commands.checks.has_permissions(moderate_members=True)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # In-memory only: recent message timestamps per (guild_id, user_id).
        # Doesn't need to survive a restart, so it isn't persisted.
        self._recent_messages: dict[tuple[int, int], deque[float]] = defaultdict(deque)

    # ---------- helpers ----------

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

    # ---------- config ----------

    @app_commands.command(description="Set the channel moderation actions get logged to.")
    @app_commands.describe(channel="The channel to send mod-log messages to")
    @app_commands.checks.has_permissions(administrator=True)
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        g = store.guild(interaction.guild_id)
        g["config"]["log_channel_id"] = channel.id
        await store.save()
        await interaction.response.send_message(f"Mod-log channel set to {channel.mention}.", ephemeral=True)

    # ---------- core moderation ----------

    @app_commands.command(description="Kick a member from the server.")
    @app_commands.describe(member="Who to kick", reason="Why they're being kicked")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given") -> None:
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("You can't kick someone with an equal or higher role.", ephemeral=True)
            return
        try:
            await member.kick(reason=f"{interaction.user} ({interaction.user.id}): {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to kick that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"👢 Kicked **{member}**. Reason: {reason}")
        await self._log(interaction.guild, discord.Embed(
            title="Member kicked", color=discord.Color.orange(),
            description=f"**Member:** {member} ({member.id})\n**By:** {interaction.user}\n**Reason:** {reason}",
        ))

    @app_commands.command(description="Ban a member from the server.")
    @app_commands.describe(member="Who to ban", reason="Why they're being banned", delete_days="Days of their messages to delete (0-7)")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given", delete_days: app_commands.Range[int, 0, 7] = 0) -> None:
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("You can't ban someone with an equal or higher role.", ephemeral=True)
            return
        try:
            await member.ban(reason=f"{interaction.user} ({interaction.user.id}): {reason}", delete_message_days=delete_days)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to ban that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔨 Banned **{member}**. Reason: {reason}")
        await self._log(interaction.guild, discord.Embed(
            title="Member banned", color=discord.Color.red(),
            description=f"**Member:** {member} ({member.id})\n**By:** {interaction.user}\n**Reason:** {reason}",
        ))

    @app_commands.command(description="Unban a user by their user ID.")
    @app_commands.describe(user_id="The numeric Discord user ID to unban")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("That doesn't look like a valid user ID.", ephemeral=True)
            return
        try:
            user = discord.Object(id=uid)
            await interaction.guild.unban(user, reason=f"Unbanned by {interaction.user}")
        except discord.NotFound:
            await interaction.response.send_message("That user isn't banned here.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to unban.", ephemeral=True)
            return
        await interaction.response.send_message(f"Unbanned user ID `{uid}`.")

    @app_commands.command(description="Timeout (mute) a member for a set duration.")
    @app_commands.describe(member="Who to timeout", minutes="How many minutes", reason="Why")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason given") -> None:
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("You can't timeout someone with an equal or higher role.", ephemeral=True)
            return
        try:
            await member.timeout(timedelta(minutes=minutes), reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to timeout that member.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔇 Timed out **{member}** for {minutes} minute(s). Reason: {reason}")
        await self._log(interaction.guild, discord.Embed(
            title="Member timed out", color=discord.Color.orange(),
            description=f"**Member:** {member} ({member.id})\n**By:** {interaction.user}\n**Duration:** {minutes}m\n**Reason:** {reason}",
        ))

    @app_commands.command(description="Remove an active timeout from a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member) -> None:
        try:
            await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to do that.", ephemeral=True)
            return
        await interaction.response.send_message(f"Removed timeout from **{member}**.")

    # ---------- warnings ----------

    @app_commands.command(description="Warn a member. Warnings are saved and viewable with /warnings.")
    @_mod_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        g = store.guild(interaction.guild_id)
        g["warnings"].setdefault(str(member.id), []).append({
            "reason": reason, "moderator_id": interaction.user.id, "timestamp": time.time(),
        })
        await store.save()
        count = len(g["warnings"][str(member.id)])
        await interaction.response.send_message(f"⚠️ Warned **{member}** (warning #{count}). Reason: {reason}")
        await self._log(interaction.guild, discord.Embed(
            title="Member warned", color=discord.Color.yellow(),
            description=f"**Member:** {member} ({member.id})\n**By:** {interaction.user}\n**Reason:** {reason}\n**Total warnings:** {count}",
        ))
        try:
            await member.send(f"You were warned in **{interaction.guild.name}**: {reason}")
        except discord.Forbidden:
            pass

    @app_commands.command(description="List a member's warnings.")
    @_mod_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        g = store.guild(interaction.guild_id)
        entries = g["warnings"].get(str(member.id), [])
        if not entries:
            await interaction.response.send_message(f"**{member}** has no warnings.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Warnings for {member}", color=discord.Color.yellow())
        for i, w in enumerate(entries[-25:], start=1):
            mod = interaction.guild.get_member(w["moderator_id"])
            embed.add_field(
                name=f"#{i} — <t:{int(w['timestamp'])}:R>",
                value=f"{w['reason']}\n— by {mod.mention if mod else w['moderator_id']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        g = store.guild(interaction.guild_id)
        had = bool(g["warnings"].pop(str(member.id), None))
        await store.save()
        if had:
            await interaction.response.send_message(f"Cleared warnings for **{member}**.")
        else:
            await interaction.response.send_message(f"**{member}** had no warnings.", ephemeral=True)

    # ---------- channel tools ----------

    @app_commands.command(description="Delete a number of recent messages from this channel.")
    @app_commands.describe(amount="How many messages to delete (max 100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]) -> None:
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)

    @app_commands.command(description="Set slowmode for this channel (0 to disable).")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]) -> None:
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("Slowmode disabled.")
        else:
            await interaction.response.send_message(f"Slowmode set to {seconds}s.")

    @app_commands.command(description="Lock this channel so @everyone can't send messages.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Channel locked.")

    @app_commands.command(description="Unlock this channel for @everyone.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Channel unlocked.")

    # ---------- config: anti-spam ----------

    @app_commands.command(description="Configure the automatic anti-spam filter.")
    @app_commands.describe(
        enabled="Turn the filter on or off",
        max_messages="Messages allowed within the time window before action is taken",
        window_seconds="The time window, in seconds",
        timeout_seconds="How long to timeout someone who trips the filter",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def antispam(
        self, interaction: discord.Interaction,
        enabled: bool | None = None,
        max_messages: app_commands.Range[int, 2, 30] | None = None,
        window_seconds: app_commands.Range[int, 1, 60] | None = None,
        timeout_seconds: app_commands.Range[int, 10, 3600] | None = None,
    ) -> None:
        cfg = store.guild(interaction.guild_id)["config"]
        if enabled is not None:
            cfg["antispam_enabled"] = enabled
        if max_messages is not None:
            cfg["antispam_max_messages"] = max_messages
        if window_seconds is not None:
            cfg["antispam_window_seconds"] = window_seconds
        if timeout_seconds is not None:
            cfg["antispam_timeout_seconds"] = timeout_seconds
        await store.save()
        await interaction.response.send_message(
            f"Anti-spam: **{'on' if cfg['antispam_enabled'] else 'off'}** — "
            f"{cfg['antispam_max_messages']} msgs / {cfg['antispam_window_seconds']}s → "
            f"{cfg['antispam_timeout_seconds']}s timeout.",
            ephemeral=True,
        )

    # ---------- listener: anti-spam ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        cfg = store.guild(message.guild.id)["config"]
        if not cfg.get("antispam_enabled", True):
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.manage_messages:
            return  # don't throttle mods/staff

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        window = cfg.get("antispam_window_seconds", 5)
        dq = self._recent_messages[key]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()

        if len(dq) > cfg.get("antispam_max_messages", 5):
            dq.clear()  # reset so we don't re-trigger every single message
            timeout_s = cfg.get("antispam_timeout_seconds", 60)
            try:
                await message.author.timeout(timedelta(seconds=timeout_s), reason="Automatic anti-spam")
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                def _is_recent(m: discord.Message) -> bool:
                    return m.author.id == message.author.id and (discord.utils.utcnow() - m.created_at).total_seconds() < window + 2
                await message.channel.purge(limit=50, check=_is_recent)
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await message.channel.send(
                    f"⏳ {message.author.mention} was timed out for {timeout_s}s for sending messages too fast.",
                    delete_after=10,
                )
            except discord.HTTPException:
                pass
            await self._log(message.guild, discord.Embed(
                title="Anti-spam triggered", color=discord.Color.dark_orange(),
                description=f"**Member:** {message.author} ({message.author.id})\n**Action:** {timeout_s}s timeout + message cleanup",
            ))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
