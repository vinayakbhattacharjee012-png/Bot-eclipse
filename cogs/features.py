"""/feature: browse the 50,000-entry preset catalog and switch modules on or off for this server."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import catalog, features, registry
from utils.storage import store

_CATEGORY_CHOICES = [app_commands.Choice(name=c, value=c) for c in catalog.CATEGORIES]


async def _id_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=fid, value=fid) for fid in catalog.search(current, limit=25)]


class FeatureCog(commands.Cog):
    feature = app_commands.Group(name="feature", description="Browse the preset catalog and switch modules on or off", guild_only=True)

    @feature.command(name="list", description="Show every module and whether it is on here.")
    async def list_modules(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        lines = [
            f"{'🟢' if features.enabled(gid, c) else '⚪'} `{c}` — {catalog.PER_CATEGORY:,} presets"
            for c in catalog.CATEGORIES
        ]
        embed = discord.Embed(
            title=f"Modules · {catalog.TOTAL:,} catalog entries",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Admins: /feature toggle turns a module on or off.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @feature.command(name="info", description="Explain one catalog id, e.g. moderation.ban.server.5.")
    @app_commands.describe(feature_id="Format: category.action.scope.strength")
    @app_commands.autocomplete(feature_id=_id_choices)
    async def info(self, interaction: discord.Interaction, feature_id: str) -> None:
        entry = catalog.lookup(feature_id)
        if entry is None:
            await interaction.response.send_message(
                "That isn't a catalog id. The format is `category.action.scope.strength`, "
                "for example `moderation.ban.server.5` (strength 1 to 10).",
                ephemeral=True,
            )
            return
        on = features.enabled(interaction.guild_id, entry.category)
        handler = features.CATEGORY_HANDLER.get(entry.category)
        if handler is None:
            backing = "Handled by the core cog for this module."
        else:
            loaded = "loaded" if handler in registry.loaded() else "loads on first use"
            backing = f"Backed by the `{handler}` handler ({loaded})."
        await interaction.response.send_message(
            f"**{entry.id}**\n"
            f"Category: `{entry.category}` is {'on' if on else 'off'} here.\n"
            f"Action: {entry.action} · Scope: {entry.scope} · Strength: {entry.strength}/10\n"
            f"{backing}\n"
            "Catalog entries are presets. Runtime behaviour follows the module switch, not each entry.",
            ephemeral=True,
        )

    @feature.command(name="search", description="Find catalog ids containing some text.")
    @app_commands.describe(query="Text to look for, e.g. ban, economy or strength 9")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        hits = catalog.search(query, limit=25)
        if not hits:
            await interaction.response.send_message("Nothing matched.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Showing {len(hits)} of up to 25 matches:\n" + "\n".join(f"`{h}`" for h in hits),
            ephemeral=True,
        )

    @feature.command(name="toggle", description="Turn a whole module on or off for this server.")
    @app_commands.describe(category="The module to switch", enabled="On or off")
    @app_commands.choices(category=_CATEGORY_CHOICES)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction, category: app_commands.Choice[str], enabled: bool) -> None:
        features.set_enabled(interaction.guild_id, category.value, enabled)
        await store.save()
        state = "on" if enabled else "off"
        await interaction.response.send_message(f"The **{category.value}** module is now **{state}** on this server.")

    @feature.command(name="stats", description="Catalog size, and which handlers are loaded.")
    async def stats(self, interaction: discord.Interaction) -> None:
        lines = [
            (
                f"Catalog: **{catalog.TOTAL:,}** entries = {len(catalog.CATEGORIES)} categories × "
                f"{len(catalog.ACTIONS)} actions × {len(catalog.SCOPES)} scopes × {len(catalog.STRENGTHS)} strengths."
            ),
            f"Handlers registered: {len(registry.registered())} · loaded so far: {len(registry.loaded())}",
            "Slash commands are added once per group, not once per catalog entry, to stay inside Discord's limits.",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FeatureCog())
