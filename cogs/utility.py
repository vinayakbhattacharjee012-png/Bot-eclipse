"""General-purpose commands: ping, info lookups, polls, announcements,
reaction roles, and a help command."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(description="Check the bot's latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"🏓 Pong! `{round(self.bot.latency * 1000)}ms`")

    @app_commands.command(description="Show info about this server.")
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        embed = discord.Embed(title=guild.name, color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=str(guild.owner) if guild.owner else "Unknown", inline=True)
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        embed.add_field(name="Text channels", value=str(len(guild.text_channels)), inline=True)
        embed.add_field(name="Voice channels", value=str(len(guild.voice_channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.set_footer(text=f"Server ID: {guild.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show info about a member.")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        embed = discord.Embed(title=str(member), color=member.color or discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined server", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Account created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        top_roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"][:10]
        embed.add_field(name="Roles", value=", ".join(top_roles) if top_roles else "None", inline=False)
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Get a user's avatar.")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        embed = discord.Embed(title=f"{member}'s avatar", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Start a quick reaction poll.")
    @app_commands.describe(
        question="The poll question",
        option1="First option", option2="Second option",
        option3="Third option (optional)", option4="Fourth option (optional)",
        option5="Fifth option (optional)",
    )
    async def poll(
        self, interaction: discord.Interaction, question: str,
        option1: str, option2: str,
        option3: str | None = None, option4: str | None = None, option5: str | None = None,
    ) -> None:
        options = [o for o in (option1, option2, option3, option4, option5) if o]
        description = "\n".join(f"{NUMBER_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
        embed = discord.Embed(title=f"📊 {question}", description=description, color=discord.Color.blurple())
        embed.set_footer(text=f"Poll started by {interaction.user}")
        await interaction.response.send_message(embed=embed)
        sent = await interaction.original_response()
        for i in range(len(options)):
            await sent.add_reaction(NUMBER_EMOJIS[i])

    @app_commands.command(description="Send an announcement embed to a channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str) -> None:
        embed = discord.Embed(title=title, description=message, color=discord.Color.blurple())
        embed.set_footer(text=f"Announced by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to post in that channel.", ephemeral=True)
            return
        await interaction.response.send_message(f"Announcement sent to {channel.mention}.", ephemeral=True)

    @app_commands.command(description="Add a reaction-role to a message: react with the emoji to get the role.")
    @app_commands.describe(message_id="The message ID to attach the reaction-role to", emoji="The emoji to react with", role="The role to give")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def reactionrole(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("That doesn't look like a valid message ID.", ephemeral=True)
            return
        try:
            message = await interaction.channel.fetch_message(mid)
        except discord.NotFound:
            await interaction.response.send_message("Couldn't find that message in this channel.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message("That role is above my top role, so I can't assign it.", ephemeral=True)
            return

        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message("I couldn't react with that emoji — make sure it's a standard emoji or one from this server.", ephemeral=True)
            return

        g = store.guild(interaction.guild_id)
        g["reaction_roles"].setdefault(str(mid), {})[emoji] = role.id
        await store.save()
        await interaction.response.send_message(f"Reacting with {emoji} on that message now gives {role.mention}.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction_role(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction_role(payload, add=False)

    async def _handle_reaction_role(self, payload: discord.RawReactionActionEvent, add: bool) -> None:
        if not payload.guild_id or payload.user_id == self.bot.user.id:
            return
        g = store.guild(payload.guild_id)
        mapping = g["reaction_roles"].get(str(payload.message_id))
        if not mapping:
            return
        emoji_key = str(payload.emoji)
        role_id = mapping.get(emoji_key)
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id) if guild else None
        member = guild.get_member(payload.user_id) if guild else None
        if not role or not member:
            return
        try:
            if add:
                await member.add_roles(role, reason="Reaction role")
            else:
                await member.remove_roles(role, reason="Reaction role removed")
        except discord.Forbidden:
            pass

    @app_commands.command(name="help", description="List everything this bot can do.")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Bot commands", color=discord.Color.blurple())
        embed.add_field(
            name="🛡️ Moderation",
            value="`/kick` `/ban` `/unban` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarnings`\n"
                  "`/purge` `/lock` `/unlock` `/slowmode` `/setlogchannel` `/antispam` `/antiraid`",
            inline=False,
        )
        embed.add_field(
            name="📈 Leveling",
            value="`/rank` `/leaderboard` `/setlevelchannel` `/setlevelrole` `/removelevelrole` `/setxp`",
            inline=False,
        )
        embed.add_field(
            name="🧰 Utility",
            value="`/ping` `/serverinfo` `/userinfo` `/avatar` `/poll` `/announce` `/reactionrole`",
            inline=False,
        )
        embed.add_field(name="✅ Verification", value="`/setupverification`", inline=False)
        embed.add_field(name="💤 AFK", value="`/afk`", inline=False)
        embed.set_footer(text="Admin-only commands won't show up in the Discord UI unless you have permission.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
