"""Command tree that enforces per-server module switches before any slash command runs."""
from __future__ import annotations

import discord
from discord import app_commands

from utils import features


class EclipseTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        command = interaction.command
        if interaction.guild_id is None or command is None:
            return True
        category = features.category_for(command.qualified_name)
        if category is None or features.enabled(interaction.guild_id, category):
            return True
        await interaction.response.send_message(
            f"The **{category}** module is turned off on this server. "
            "An admin can turn it back on with `/feature toggle`.",
            ephemeral=True,
        )
        return False
