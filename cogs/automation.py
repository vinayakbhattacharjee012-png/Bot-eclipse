"""Automation: auto-responders and custom commands, reminders, welcome/goodbye/boost messages,
a starboard, and embed posting. Reminders use the persisted scheduler, so they survive restarts."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import features, scheduler
from utils.cooldowns import Bucket
from utils.storage import store

TRIGGER_MODES = ("exact", "contains", "command")
STARBOARD_EMOJI = "⭐"
RESPONDER_COOLDOWN = Bucket(limit=1, per=5)
MAX_STARBOARD_POSTED = 500


def _sec(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("automation", {})
    sec.setdefault("responders", {})   # trigger -> {"response", "mode"}
    sec.setdefault("welcome", None)    # {"channel_id", "message"}
    sec.setdefault("goodbye", None)
    sec.setdefault("boost", None)
    sec.setdefault("starboard", None)  # {"channel_id", "threshold"}
    sec.setdefault("starboard_posted", {})
    return sec


def _fill(template: str, member: discord.Member) -> str:
    guild = member.guild
    return (
        template.replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{server}", guild.name)
        .replace("{members}", str(guild.member_count or 0))
    )


@scheduler.handler("remind")
async def _send_reminder(bot, guild_id: int, payload: dict) -> None:
    channel = bot.get_channel(payload["channel_id"])
    if channel is None:
        return
    await channel.send(
        f"<@{payload['user_id']}> reminder: {payload['text']}",
        allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
    )


class Automation(commands.Cog):
    automation = app_commands.Group(name="automation", description="Responders, reminders, welcome messages, starboard and embeds", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        scheduler.start(self.bot)

    # ---------- listeners ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if not features.enabled(message.guild.id, "automation"):
            return
        responders = _sec(message.guild.id)["responders"]
        if not responders:
            return
        text = message.content.strip()
        lowered = text.lower()
        for trigger, entry in responders.items():
            mode = entry["mode"]
            if mode == "exact":
                hit = lowered == trigger
            elif mode == "contains":
                hit = trigger in lowered
            else:
                hit = lowered == "!" + trigger
            if not hit:
                continue
            if RESPONDER_COOLDOWN.hit((message.channel.id, trigger)):
                return
            try:
                await message.channel.send(entry["response"][:1900], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
            return

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._greet(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._greet(member, "goodbye")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.premium_since is None and after.premium_since is not None:
            await self._greet(after, "boost")

    async def _greet(self, member: discord.Member, kind: str) -> None:
        if member.bot or not features.enabled(member.guild.id, "welcome"):
            return
        cfg = _sec(member.guild.id)[kind]
        if not cfg:
            return
        channel = member.guild.get_channel(cfg["channel_id"])
        if channel is None:
            return
        try:
            await channel.send(_fill(cfg["message"], member), allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or str(payload.emoji) != STARBOARD_EMOJI:
            return
        if not features.enabled(payload.guild_id, "starboard"):
            return
        sec = _sec(payload.guild_id)
        cfg = sec["starboard"]
        if not cfg or payload.channel_id == cfg["channel_id"]:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        source = guild.get_channel(payload.channel_id)
        if source is None:
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        stars = next((r.count for r in message.reactions if str(r.emoji) == STARBOARD_EMOJI), 0)
        if stars < cfg["threshold"] or str(message.id) in sec["starboard_posted"]:
            return
        board = guild.get_channel(cfg["channel_id"])
        if board is None:
            return
        embed = discord.Embed(description=message.content[:1000] or "(no text)", color=discord.Color.gold(), timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url})")
        try:
            posted = await board.send(f"{STARBOARD_EMOJI} **{stars}** in {source.mention}", embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return
        posted_map = sec["starboard_posted"]
        posted_map[str(message.id)] = posted.id
        if len(posted_map) > MAX_STARBOARD_POSTED:
            for old in list(posted_map)[: len(posted_map) - MAX_STARBOARD_POSTED]:
                posted_map.pop(old, None)
        await store.save()

    # ---------- responders and custom commands ----------

    @automation.command(name="responder_add", description="Add an auto-reply. Mode 'command' answers !trigger.")
    @app_commands.describe(trigger="The word or phrase to watch for (or the command name)", response="What the bot replies", mode="How to match")
    @app_commands.choices(mode=[app_commands.Choice(name=m, value=m) for m in TRIGGER_MODES])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def responder_add(
        self, interaction: discord.Interaction, trigger: app_commands.Range[str, 1, 40], response: app_commands.Range[str, 1, 1000],
        mode: app_commands.Choice[str] | None = None,
    ) -> None:
        key = trigger.strip().lower().lstrip("!")
        if not key or " " in key and (mode and mode.value == "command"):
            await interaction.response.send_message("Command names can't contain spaces.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        sec["responders"][key] = {"response": response, "mode": mode.value if mode else "exact"}
        await store.save()
        await interaction.response.send_message(f"Responder **{key}** saved.", ephemeral=True)

    @automation.command(name="responder_remove", description="Remove an auto-reply or custom command.")
    @app_commands.describe(trigger="The trigger to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def responder_remove(self, interaction: discord.Interaction, trigger: str) -> None:
        removed = _sec(interaction.guild_id)["responders"].pop(trigger.strip().lower().lstrip("!"), None)
        await store.save()
        await interaction.response.send_message("Removed." if removed else "No responder with that trigger.", ephemeral=True)

    @automation.command(name="responder_list", description="List auto-replies and custom commands.")
    async def responder_list(self, interaction: discord.Interaction) -> None:
        responders = _sec(interaction.guild_id)["responders"]
        if not responders:
            await interaction.response.send_message("No responders yet.", ephemeral=True)
            return
        lines = [f"`{t}` ({e['mode']}) → {e['response'][:60]}" for t, e in sorted(responders.items())]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    # ---------- reminders ----------

    @automation.command(description="Remind you in this channel after some minutes.")
    @app_commands.describe(minutes="How many minutes from now (1 to 10080)", text="What to remind you about")
    async def remind(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10080], text: app_commands.Range[str, 1, 300]) -> None:
        scheduler.add(interaction.guild_id, "remind", time.time() + minutes * 60, {
            "channel_id": interaction.channel_id, "user_id": interaction.user.id, "text": text,
        })
        await store.save()
        await interaction.response.send_message(f"Okay. I'll remind you in {minutes} minute(s).", ephemeral=True)

    # ---------- welcome, goodbye, boost, starboard ----------

    @automation.command(description="Post a welcome message when someone joins. Use {user}, {name}, {server}, {members}.")
    @app_commands.describe(channel="Where to post it", message="The message text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome(self, interaction: discord.Interaction, channel: discord.TextChannel, message: app_commands.Range[str, 1, 500]) -> None:
        _sec(interaction.guild_id)["welcome"] = {"channel_id": channel.id, "message": message}
        await store.save()
        await interaction.response.send_message(f"Welcome messages will go to {channel.mention}.", ephemeral=True)

    @automation.command(description="Post a message when someone leaves. Same placeholders as welcome.")
    @app_commands.describe(channel="Where to post it", message="The message text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye(self, interaction: discord.Interaction, channel: discord.TextChannel, message: app_commands.Range[str, 1, 500]) -> None:
        _sec(interaction.guild_id)["goodbye"] = {"channel_id": channel.id, "message": message}
        await store.save()
        await interaction.response.send_message(f"Goodbye messages will go to {channel.mention}.", ephemeral=True)

    @automation.command(description="Post a message when someone boosts the server.")
    @app_commands.describe(channel="Where to post it", message="The message text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def boost(self, interaction: discord.Interaction, channel: discord.TextChannel, message: app_commands.Range[str, 1, 500]) -> None:
        _sec(interaction.guild_id)["boost"] = {"channel_id": channel.id, "message": message}
        await store.save()
        await interaction.response.send_message(f"Boost messages will go to {channel.mention}.", ephemeral=True)

    @automation.command(description="Starboard: messages with enough ⭐ reactions get posted to a channel.")
    @app_commands.describe(channel="The starboard channel (leave empty to turn it off)", threshold="Stars needed (1 to 50)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def starboard(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None, threshold: app_commands.Range[int, 1, 50] = 3) -> None:
        sec = _sec(interaction.guild_id)
        sec["starboard"] = {"channel_id": channel.id, "threshold": threshold} if channel else None
        await store.save()
        text = f"Starboard on: {channel.mention} at {threshold} ⭐." if channel else "Starboard is off."
        await interaction.response.send_message(text, ephemeral=True)

    # ---------- embeds ----------

    @automation.command(description="Post an embed to a channel.")
    @app_commands.describe(channel="Where to post it", title="Embed title", description="Embed text", color="Hex colour such as 06b6d4 (optional)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def embed(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
        title: app_commands.Range[str, 1, 256], description: app_commands.Range[str, 1, 4000],
        color: app_commands.Range[str, 6, 6] | None = None,
    ) -> None:
        try:
            colour = discord.Colour(int(color, 16)) if color else discord.Colour.blurple()
        except ValueError:
            await interaction.response.send_message("The colour must be six hex digits, like 06b6d4.", ephemeral=True)
            return
        embed = discord.Embed(title=title, description=description, colour=colour)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await interaction.response.send_message("I can't post in that channel.", ephemeral=True)
            return
        await interaction.response.send_message(f"Posted to {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Automation(bot))
