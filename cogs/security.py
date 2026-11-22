"""Anti-nuke: watches for bursts of dangerous actions (mass channel/role create or delete,
mass bans or kicks, webhook creation, bot additions). When one actor crosses the threshold,
it strips their roles, optionally adds a quarantine role, and logs an incident.

Not included: automatic rollback of deleted channels or roles. Discord has no undo, and
restoring them needs snapshots this build does not take (see /backup export)."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import audit, features
from utils.cooldowns import SlidingCounter
from utils.storage import store

INCIDENT_COOLDOWN = 60
AUDIT_MAX_AGE = 15
DEFAULTS: dict[str, object] = {
    "enabled": True, "threshold": 3, "window": 10, "quarantine_role_id": None,
    "whitelist_users": [], "whitelist_roles": [],
}


def _cfg(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("security", {})
    for k, v in DEFAULTS.items():
        sec.setdefault(k, list(v) if isinstance(v, list) else v)
    return sec


class Security(commands.Cog):
    security = app_commands.Group(name="security", description="Anti-nuke: detect and contain mass dangerous actions", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._counts = SlidingCounter()
        self._last_incident: dict[tuple[int, int], float] = {}

    # ---------- detection helpers ----------

    async def _actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None):
        """The user who performed `action`, if the audit log shows it happened just now."""
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > AUDIT_MAX_AGE:
                    return None
                return entry.user
        except discord.HTTPException:
            return None
        return None

    def _whitelisted(self, guild: discord.Guild, actor: discord.abc.User) -> bool:
        if actor.id in (guild.owner_id, self.bot.user.id):
            return True
        sec = _cfg(guild.id)
        if actor.id in sec["whitelist_users"]:
            return True
        member = guild.get_member(actor.id)
        return bool(member and any(r.id in sec["whitelist_roles"] for r in member.roles))

    async def _record(self, guild: discord.Guild, action: discord.AuditLogAction, label: str, target_id: int | None = None) -> None:
        if not features.enabled(guild.id, "security"):
            return
        cfg = _cfg(guild.id)
        if not cfg.get("enabled", True):
            return
        actor = await self._actor(guild, action, target_id)
        if actor is None or self._whitelisted(guild, actor):
            return
        key = (guild.id, actor.id)
        count = self._counts.add((guild.id, actor.id, label), cfg["window"], time.monotonic())
        if count < cfg["threshold"]:
            return
        last = self._last_incident.get(key, 0)
        if time.monotonic() - last < INCIDENT_COOLDOWN:
            return
        self._last_incident[key] = time.monotonic()
        await self._contain(guild, actor, label, count)

    async def _contain(self, guild: discord.Guild, actor: discord.abc.User, label: str, count: int) -> None:
        cfg = _cfg(guild.id)
        member = guild.get_member(actor.id)
        result = []
        if member is not None:
            if member.bot:
                try:
                    await member.kick(reason=f"Anti-nuke: {label} burst")
                    result.append("kicked the bot")
                except discord.HTTPException:
                    result.append("couldn't kick the bot")
            else:
                try:
                    await member.edit(roles=[], reason=f"Anti-nuke: {label} burst ({count} in window)")
                    result.append("removed all roles")
                except discord.HTTPException:
                    result.append("couldn't remove roles (check my role position)")
                quarantine = guild.get_role(cfg["quarantine_role_id"]) if cfg["quarantine_role_id"] else None
                if quarantine is not None:
                    try:
                        await member.add_roles(quarantine, reason="Anti-nuke quarantine")
                        result.append(f"gave quarantine role {quarantine.name}")
                    except discord.HTTPException:
                        result.append("couldn't give the quarantine role")
        else:
            result.append("actor isn't in the server anymore")
        await audit.record(
            guild, "anti-nuke",
            f"{actor} ({actor.id}) did **{label}** {count} times in {cfg['window']}s. Response: {', '.join(result)}.",
            actor_id=actor.id,
        )

    # ---------- listeners ----------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self._record(channel.guild, discord.AuditLogAction.channel_create, "channel create")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self._record(channel.guild, discord.AuditLogAction.channel_delete, "channel delete")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self._record(role.guild, discord.AuditLogAction.role_create, "role create")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._record(role.guild, discord.AuditLogAction.role_delete, "role delete")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await self._record(guild, discord.AuditLogAction.ban, "ban", target_id=user.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        # A removal only counts when the audit log says it was a kick.
        await self._record(member.guild, discord.AuditLogAction.kick, "kick", target_id=member.id)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        await self._record(channel.guild, discord.AuditLogAction.webhook_create, "webhook create")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            await self._record(member.guild, discord.AuditLogAction.bot_add, "bot add", target_id=member.id)

    # ---------- configuration ----------

    @security.command(description="Show anti-nuke settings and recent incidents.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        cfg = _cfg(interaction.guild_id)
        incidents = [e for e in store.guild(interaction.guild_id).get("audit", []) if e["action"] == "anti-nuke"][-3:]
        lines = [
            f"Enabled: **{cfg['enabled']}**",
            f"Threshold: {cfg['threshold']} actions in {cfg['window']}s",
            f"Quarantine role: {'set' if cfg['quarantine_role_id'] else 'not set'}",
            f"Whitelisted users: {len(cfg['whitelist_users'])} · roles: {len(cfg['whitelist_roles'])}",
            "Recent incidents: " + (" · ".join(e["detail"][:120] for e in incidents) or "none"),
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @security.command(description="Set how many dangerous actions in how many seconds count as a burst.")
    @app_commands.describe(threshold="Actions that trigger a response (2 to 50)", window="Time window in seconds (3 to 120)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def threshold(self, interaction: discord.Interaction, threshold: app_commands.Range[int, 2, 50], window: app_commands.Range[int, 3, 120]) -> None:
        cfg = _cfg(interaction.guild_id)
        cfg["threshold"], cfg["window"] = threshold, window
        await store.save()
        await interaction.response.send_message(f"Burst = {threshold} actions in {window}s.", ephemeral=True)

    @security.command(description="Set the role given to contained accounts (optional).")
    @app_commands.describe(role="The quarantine role (leave empty to clear)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def quarantine_role(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        _cfg(interaction.guild_id)["quarantine_role_id"] = role.id if role else None
        await store.save()
        await interaction.response.send_message(f"Quarantine role {'set to ' + role.name if role else 'cleared'}.", ephemeral=True)

    @security.command(description="Exempt a member or role from anti-nuke.")
    @app_commands.describe(member="A member to exempt", role="A role to exempt", allow="True to exempt, False to remove the exemption")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def whitelist(self, interaction: discord.Interaction, allow: bool, member: discord.Member | None = None, role: discord.Role | None = None) -> None:
        cfg = _cfg(interaction.guild_id)
        if member is None and role is None:
            await interaction.response.send_message("Pick a member or a role.", ephemeral=True)
            return
        if member is not None:
            ids = cfg["whitelist_users"]
            if allow and member.id not in ids:
                ids.append(member.id)
            elif not allow and member.id in ids:
                ids.remove(member.id)
        if role is not None:
            ids = cfg["whitelist_roles"]
            if allow and role.id not in ids:
                ids.append(role.id)
            elif not allow and role.id in ids:
                ids.remove(role.id)
        await store.save()
        await interaction.response.send_message("Whitelist updated.", ephemeral=True)

    @security.command(description="Turn anti-nuke on or off.")
    @app_commands.describe(enabled="On or off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(self, interaction: discord.Interaction, enabled: bool) -> None:
        _cfg(interaction.guild_id)["enabled"] = enabled
        await store.save()
        await interaction.response.send_message(f"Anti-nuke is now **{'on' if enabled else 'off'}**.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Security(bot))
