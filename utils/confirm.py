"""Confirm/cancel buttons for consequential actions. Only the named person can press them."""
from __future__ import annotations

import discord


class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.value: bool | None = None  # True = confirmed, False = cancelled, None = timed out

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person this is for can answer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="Confirmed.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)
