"""Button-based verification: post an embed with a Verify button, and
clicking it gives the member a role. The view is persistent, so it keeps
working across bot restarts."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store

VERIFY_BUTTON_ID = "verify_button:click"


class VerifyView(discord.ui.View):
    """A persistent view -- timeout=None and a fixed custom_id so it keeps
    responding to clicks forever, even after the bot restarts."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id=VERIFY_BUTTON_ID)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        g = store.guild(interaction.guild_id)
        role_id = g["config"].get("verification_role_id")
        if not role_id:
            await interaction.response.send_message("Verification isn't set up here yet.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("The verification role no longer exists — ask a mod to re-run setup.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("You're already verified!", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Self-verified")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to give you that role — ask a mod for help.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ You're verified! Welcome to **{interaction.guild.name}**.", ephemeral=True)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(VerifyView())  # register so it survives restarts

    @app_commands.command(description="Post a verification message in this channel.")
    @app_commands.describe(
        role="The role members get when they click Verify",
        channel="Where to post the message (defaults to this channel)",
        message="Custom text for the embed (optional)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def setupverification(
        self, interaction: discord.Interaction, role: discord.Role,
        channel: discord.TextChannel | None = None,
        message: str | None = None,
    ) -> None:
        channel = channel or interaction.channel
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "That role is higher than or equal to my own top role, so I can't assign it. "
                "Move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Verify to get access",
            description=message or "Click the button below to verify and unlock the rest of the server.",
            color=discord.Color.green(),
        )
        sent = await channel.send(embed=embed, view=VerifyView())

        g = store.guild(interaction.guild_id)
        g["config"]["verification_role_id"] = role.id
        g["config"]["verification_channel_id"] = channel.id
        g["config"]["verification_message_id"] = sent.id
        await store.save()

        await interaction.response.send_message(f"Verification message posted in {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
