"""Support tickets: open a private channel, claim it, and close it with a saved transcript."""
from __future__ import annotations

import io

import discord
from discord import app_commands
from discord.ext import commands

from utils.confirm import ConfirmView
from utils.storage import store

TRANSCRIPT_LIMIT = 500


def _sec(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("tickets", {})
    sec.setdefault("category_id", None)
    sec.setdefault("counter", 0)
    sec.setdefault("open", {})
    return sec


def _is_staff(member: discord.Member) -> bool:
    return member.guild_permissions.manage_messages


def _open_for(sec: dict, user_id: int) -> int | None:
    for channel_id, info in sec["open"].items():
        if info["owner"] == user_id:
            return int(channel_id)
    return None


class Tickets(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Support tickets: open, claim and close", guild_only=True)

    @ticket.command(description="Admin: choose the category new ticket channels are created in.")
    @app_commands.describe(category="Category for new tickets (leave empty to create them at the top level)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup(self, interaction: discord.Interaction, category: discord.CategoryChannel | None = None) -> None:
        sec = _sec(interaction.guild_id)
        sec["category_id"] = category.id if category else None
        await store.save()
        where = f"in **{category.name}**" if category else "at the top level"
        await interaction.response.send_message(f"New tickets will be created {where}.", ephemeral=True)

    @ticket.command(description="Open a private ticket with the staff team.")
    @app_commands.describe(reason="What you need help with")
    async def open(self, interaction: discord.Interaction, reason: app_commands.Range[str, 1, 300]) -> None:
        sec = _sec(interaction.guild_id)
        existing = _open_for(sec, interaction.user.id)
        if existing is not None:
            await interaction.response.send_message(f"You already have a ticket open: <#{existing}>.", ephemeral=True)
            return
        guild = interaction.guild
        sec["counter"] += 1
        number = sec["counter"]
        category = guild.get_channel(sec["category_id"]) if sec["category_id"] else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        safe_name = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c == "-")[:20] or "member"
        try:
            channel = await guild.create_text_channel(
                f"ticket-{number:04d}-{safe_name}", category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites, reason=f"Ticket opened by {interaction.user}", topic=reason,
            )
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to create channels here.", ephemeral=True)
            return
        sec["open"][str(channel.id)] = {"owner": interaction.user.id, "claimed_by": None, "reason": reason}
        await store.save()
        await channel.send(
            f"{interaction.user.mention} opened this ticket.\n**Reason:** {reason}\n"
            "Staff can claim it with `/ticket claim`. Close it with `/ticket close` when you're done.",
            allowed_mentions=discord.AllowedMentions(users=[interaction.user]),
        )
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

    @ticket.command(description="Staff: claim this ticket so others know you're handling it.")
    async def claim(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        info = sec["open"].get(str(interaction.channel_id))
        if info is None:
            await interaction.response.send_message("This isn't an open ticket channel.", ephemeral=True)
            return
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)
            return
        if info["claimed_by"] and info["claimed_by"] != interaction.user.id:
            await interaction.response.send_message(f"Already claimed by <@{info['claimed_by']}>.", ephemeral=True)
            return
        info["claimed_by"] = interaction.user.id
        await store.save()
        await interaction.response.send_message(f"{interaction.user.display_name} is handling this ticket.")

    @ticket.command(description="Close this ticket. Saves a transcript to the mod-log channel first.")
    async def close(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        info = sec["open"].get(str(interaction.channel_id))
        if info is None:
            await interaction.response.send_message("This isn't an open ticket channel.", ephemeral=True)
            return
        if interaction.user.id != info["owner"] and not _is_staff(interaction.user):
            await interaction.response.send_message("Only the ticket owner or staff can close it.", ephemeral=True)
            return
        view = ConfirmView(owner_id=interaction.user.id, timeout=60)
        await interaction.response.send_message("Close this ticket and delete the channel? A transcript is saved first.", view=view, ephemeral=True)
        await view.wait()
        if not view.value:
            return
        channel = interaction.channel
        lines = []
        async for msg in channel.history(limit=TRANSCRIPT_LIMIT, oldest_first=True):
            stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
            text = msg.content or ""
            if msg.attachments:
                text += " " + " ".join(f"[attachment: {a.filename}]" for a in msg.attachments)
            lines.append(f"[{stamp}] {msg.author} ({msg.author.id}): {text}")
        transcript = "\n".join(lines) or "(no messages)"
        log_id = store.guild(interaction.guild_id)["config"].get("log_channel_id")
        log_channel = interaction.guild.get_channel(log_id) if log_id else None
        if log_channel is not None:
            file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"{channel.name}-transcript.txt")
            try:
                await log_channel.send(f"Ticket **{channel.name}** closed by {interaction.user}.", file=file, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
        sec["open"].pop(str(channel.id), None)
        await store.save()
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            await interaction.followup.send("I couldn't delete the channel. Check my permissions.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets())
