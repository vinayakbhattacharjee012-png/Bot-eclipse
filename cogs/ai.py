"""AI assistant commands: ask, summarize, code help and research. Every call goes through
the server-side endpoint in utils/ai_client.py. If it isn't configured, the command says so."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import registry
from utils.cooldowns import Bucket

MAX_REPLY = 1900
PER_USER = Bucket(limit=6, per=60)

SYSTEM_GENERAL = "You are a helpful assistant in a Discord server. Answer clearly and briefly."
SYSTEM_CODE = (
    "You help with programming. Explain the problem, then give a short, correct code example. "
    "Say when you are unsure."
)
SYSTEM_RESEARCH = (
    "You answer research questions from your own knowledge. You cannot browse the web. "
    "Say what you know, how confident you are, and what should be checked against a current source."
)
SYSTEM_SUMMARY = "Summarize this Discord chat. List the main points and any decisions or open questions. Keep it short."


def _clip(text: str) -> str:
    return text if len(text) <= MAX_REPLY else text[: MAX_REPLY - 1] + "…"


class AI(commands.Cog):
    ai = app_commands.Group(name="ai", description="Ask the AI assistant, summarize chat, get code help", guild_only=True)

    async def _run(self, interaction: discord.Interaction, system: str, user_text: str, max_tokens: int = 600) -> None:
        wait = PER_USER.hit(interaction.user.id)
        if wait:
            await interaction.response.send_message(f"Slow down a little. Try again in {int(wait) + 1}s.", ephemeral=True)
            return
        ai_client = registry.get("ai")
        await interaction.response.defer(thinking=True)
        try:
            reply = await ai_client.chat(system, user_text, max_tokens=max_tokens)
        except ai_client.AIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(_clip(reply or "(empty reply)"), allowed_mentions=discord.AllowedMentions.none())

    @ai.command(description="Ask the assistant any question.")
    @app_commands.describe(question="Your question")
    async def ask(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 500]) -> None:
        await self._run(interaction, SYSTEM_GENERAL, question)

    @ai.command(description="Summarize the last messages in this channel.")
    @app_commands.describe(count="How many recent messages to read (10 to 200)")
    async def summarize(self, interaction: discord.Interaction, count: app_commands.Range[int, 10, 200] = 50) -> None:
        ai_client = registry.get("ai")
        if not ai_client.configured():
            await interaction.response.send_message(ai_client.SETUP_HELP, ephemeral=True)
            return
        lines = []
        async for msg in interaction.channel.history(limit=count):
            if not msg.author.bot and msg.content:
                lines.append(f"{msg.author.display_name}: {msg.content[:300]}")
        if not lines:
            await interaction.response.send_message("There's nothing to summarize here.", ephemeral=True)
            return
        transcript = "\n".join(reversed(lines))
        await self._run(interaction, SYSTEM_SUMMARY, transcript[-12000:], max_tokens=500)

    @ai.command(description="Get help with code: an explanation and an example.")
    @app_commands.describe(question="What you are trying to do, or the error you see")
    async def code(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 1000]) -> None:
        await self._run(interaction, SYSTEM_CODE, question, max_tokens=800)

    @ai.command(description="Research question from the model's own knowledge (no live web search).")
    @app_commands.describe(question="What you want to know")
    async def research(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 500]) -> None:
        await self._run(interaction, SYSTEM_RESEARCH, question, max_tokens=800)

    @ai.command(description="Check whether the AI assistant is set up on this server.")
    async def status(self, interaction: discord.Interaction) -> None:
        ai_client = registry.get("ai")
        if ai_client.configured():
            text = f"AI is configured: {ai_client.describe()}."
        else:
            text = ai_client.SETUP_HELP
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI())
