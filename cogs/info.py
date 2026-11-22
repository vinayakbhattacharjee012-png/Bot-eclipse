"""Extra info commands: role details and a member's banner."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    info = app_commands.Group(name="info", description="Role details and member banners", guild_only=True)

    @info.command(description="Details about a role.")
    @app_commands.describe(role="The role to look at")
    async def role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        embed = discord.Embed(title=role.name, color=role.color if role.color.value else discord.Color.blurple())
        embed.add_field(name="ID", value=str(role.id), inline=True)
        embed.add_field(name="Members", value=str(len(role.members)), inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Created", value=f"<t:{int(role.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Mentionable", value="yes" if role.mentionable else "no", inline=True)
        embed.add_field(name="Shown separately", value="yes" if role.hoist else "no", inline=True)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @info.command(description="Show a member's profile banner, if they have one.")
    @app_commands.describe(member="Whose banner to show")
    async def banner(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        await interaction.response.defer()
        user = await interaction.client.fetch_user(member.id)
        if user.banner is None:
            await interaction.followup.send(f"**{member.display_name}** doesn't have a banner.")
            return
        embed = discord.Embed(title=f"{member.display_name}'s banner", color=discord.Color.blurple())
        embed.set_image(url=user.banner.url)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Info())
