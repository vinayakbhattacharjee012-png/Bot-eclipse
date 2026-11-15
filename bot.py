"""Entry point. Run this with `python bot.py`."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.keepalive import run_keepalive_server

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
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
]


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=INTENTS, help_command=None)

    async def setup_hook(self) -> None:
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:
                log.exception("Failed to load %s", ext)

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


async def run() -> None:
    # The keep-alive HTTP server runs alongside the real bot connection so
    # this can deploy as a free Render Web Service (which requires something
    # listening on $PORT) instead of a paid Background Worker. If PORT isn't
    # set (e.g. running locally), the server still starts on 8080 but nothing
    # needs to ping it.
    await asyncio.gather(
        run_keepalive_server(bot),
        bot.start(TOKEN),
    )


def main() -> None:
    if not TOKEN:
        log.error("DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token.")
        sys.exit(1)
    asyncio.run(run())


if __name__ == "__main__":
    main()
