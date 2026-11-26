"""Entry point. Run this with `python bot.py`."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils import discord_token, scheduler
from utils.keepalive import run_keepalive_server
from utils.tree import EclipseTree

load_dotenv()

DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
OWNER_LOG_CHANNEL_ID = os.getenv("OWNER_LOG_CHANNEL_ID")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

INTENTS = discord.Intents.default()
INTENTS.members = True          # needed for join events, verification, anti-raid
INTENTS.message_content = True  # needed for leveling XP and anti-spam

COGS = [
    "cogs.moderation",
    "cogs.antiraid",
    "cogs.leveling",
    "cogs.utility",
    "cogs.verification",
    "cogs.afk",
    # Eclipse modules
    "cogs.features",
    "cogs.mod_plus",
    "cogs.automod",
    "cogs.security",
    "cogs.economy",
    "cogs.games",
    "cogs.akinator",
    "cogs.anicatch",
    "cogs.tickets",
    "cogs.ai",
    "cogs.automation",
    "cogs.giveaways",
    "cogs.music",
    "cogs.backup",
    "cogs.info",
]


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=INTENTS, help_command=None, tree_cls=EclipseTree)

    async def setup_hook(self) -> None:
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:
                log.exception("Failed to load %s", ext)
        scheduler.start(self)

        if DEV_GUILD_ID:
            guild = discord.Object(id=int(DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (can take up to an hour to show up everywhere)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="over the server"))
        if OWNER_LOG_CHANNEL_ID:
            channel = self.get_channel(int(OWNER_LOG_CHANNEL_ID))
            if channel:
                try:
                    await channel.send(f"✅ Online as `{self.user}` in {len(self.guilds)} server(s).")
                except discord.HTTPException:
                    pass

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        log.exception("Prefix command error", exc_info=error)


bot = Bot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
    if isinstance(error, discord.app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    elif isinstance(error, discord.app_commands.CommandOnCooldown):
        msg = f"That's on cooldown. Try again in {error.retry_after:.1f}s."
    elif isinstance(error, discord.app_commands.BotMissingPermissions):
        msg = f"I'm missing permissions to do that: {', '.join(error.missing_permissions)}"
    else:
        msg = "Something went wrong running that command."
        log.exception("App command error in /%s", getattr(interaction.command, "name", "?"), exc_info=error)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


async def run(token: str) -> None:
    # The keep-alive HTTP server runs alongside the real bot connection so
    # this can deploy as a free Render Web Service (which requires something
    # listening on $PORT) instead of a paid Background Worker. If PORT isn't
    # set (e.g. running locally), the server still starts on 8080 but nothing
    # needs to ping it.
    async with bot:  # closes Discord's HTTP session even if login fails
        await asyncio.gather(
            run_keepalive_server(bot),
            bot.start(token),
        )


def main() -> None:
    try:
        token = discord_token.load()
    except discord_token.TokenError as exc:
        log.error("%s", exc)
        sys.exit(1)
    log.info("DISCORD_TOKEN %s", discord_token.describe(token))
    try:
        asyncio.run(run(token))
    except discord.LoginFailure:
        log.error("Discord rejected DISCORD_TOKEN. Reset it in the Developer Portal, then run: python scripts/set_token.py")
        sys.exit(1)
    except aiohttp.ClientConnectionError as exc:
        log.error("Couldn't reach Discord (%s). Check the internet connection and try again.", type(exc).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
