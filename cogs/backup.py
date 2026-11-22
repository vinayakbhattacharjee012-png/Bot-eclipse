"""Backup: export this server's bot data as JSON, and check a backup file's structure.

Restore is deliberately not included. Validation only confirms a file is well formed. It
doesn't write anything, so a bad file can't overwrite live data."""
from __future__ import annotations

import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store

MAX_BACKUP_BYTES = 5 * 1024 * 1024
EXPECTED_SECTIONS = {
    "config": dict, "levels": dict, "level_roles": dict, "warnings": dict, "reaction_roles": dict,
    "afk": dict, "economy": dict, "automod": dict, "security": dict, "automation": dict,
    "tickets": dict, "anicatch": dict, "features": dict, "audit": list, "cases": list, "jobs": list,
}


def check_backup(data: object) -> tuple[list[str], dict[str, int]]:
    """Returns (problems, item counts). An empty problems list means the file is well formed."""
    problems: list[str] = []
    counts: dict[str, int] = {}
    if not isinstance(data, dict):
        return ["top level must be a JSON object"], counts
    for key, kind in EXPECTED_SECTIONS.items():
        if key in data and not isinstance(data[key], kind):
            problems.append(f"`{key}` should be a {kind.__name__}")
        elif key in data:
            counts[key] = len(data[key])
    unknown = set(data) - set(EXPECTED_SECTIONS)
    if unknown:
        problems.append("unknown sections (ignored on restore): " + ", ".join(sorted(unknown)))
    return problems, counts


class Backup(commands.Cog):
    backup = app_commands.Group(name="backup", description="Export this server's bot data, or check a backup file", guild_only=True)

    @backup.command(description="Admin: download this server's bot data as a JSON file.")
    @app_commands.checks.has_permissions(administrator=True)
    async def export(self, interaction: discord.Interaction) -> None:
        data = dict(store.guild(interaction.guild_id))
        payload = json.dumps({"guild_id": interaction.guild_id, "data": data}, indent=2, ensure_ascii=False).encode("utf-8")
        file = discord.File(io.BytesIO(payload), filename=f"eclipse-backup-{interaction.guild_id}.json")
        await interaction.response.send_message(
            f"Backup of {len(payload):,} bytes. Keep it private: it contains member IDs and warnings.",
            file=file, ephemeral=True,
        )

    @backup.command(description="Check a backup file's structure. Does not change any data.")
    @app_commands.describe(file="A JSON file made by /backup export")
    @app_commands.checks.has_permissions(administrator=True)
    async def validate(self, interaction: discord.Interaction, file: discord.Attachment) -> None:
        if file.size > MAX_BACKUP_BYTES:
            await interaction.response.send_message("That file is larger than 5 MB.", ephemeral=True)
            return
        try:
            raw = json.loads((await file.read()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            await interaction.response.send_message("That isn't valid JSON.", ephemeral=True)
            return
        if not isinstance(raw, dict) or "data" not in raw or not isinstance(raw["data"], dict):
            await interaction.response.send_message("That isn't an Eclipse backup. It should have a `data` object.", ephemeral=True)
            return
        problems, counts = check_backup(raw["data"])
        summary = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "no known sections"
        if problems:
            text = "Problems found:\n" + "\n".join(f"• {p}" for p in problems) + f"\nSections: {summary}"
        else:
            text = f"Looks well formed. Sections: {summary}.\nRestore is not available in this build, so nothing was changed."
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backup())
