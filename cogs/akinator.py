"""Akinator-style 20-questions game. The deduction logic is in utils/akinator_engine.py.
This file is only the Discord side: buttons, edits and turn handling."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import registry


class Session(discord.ui.View):
    """One player's game. Only the player who started it can press its buttons."""

    ANSWER_BUTTONS = (
        ("Yes", "yes", discord.ButtonStyle.success),
        ("Probably", "probably", discord.ButtonStyle.primary),
        ("Don't know", "dont_know", discord.ButtonStyle.secondary),
        ("Probably not", "probably_not", discord.ButtonStyle.primary),
        ("No", "no", discord.ButtonStyle.danger),
    )

    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.eng = registry.get("akinator")
        self.game = self.eng.Game()
        self.attr: str | None = None
        self.guess: str | None = None
        self.outcome: str | None = None  # set when the game is over
        self._advance()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This game belongs to someone else. Start your own with `/akinator`.", ephemeral=True)
            return False
        return True

    # ---------- state ----------

    def _advance(self) -> None:
        """Decide the next step: a guess, a question, or giving up."""
        self.attr = self.guess = None
        if self.game.should_guess():
            lead = self.game.leader()
            if lead is None:
                self.outcome = "I give up. None of my characters fit those answers."
            else:
                self.guess = lead[0]
        else:
            self.attr = self.game.next_question()
            if self.attr is None:
                self.outcome = "I give up. I couldn't narrow it down."
        self._build()

    def _build(self) -> None:
        self.clear_items()
        if self.guess is not None:
            self._button("Yes, that's it", discord.ButtonStyle.success, self._correct)
            self._button("No, keep going", discord.ButtonStyle.danger, self._wrong)
        elif self.attr is not None:
            for label, value, style in self.ANSWER_BUTTONS:
                self._button(label, style, self._make_answer(value))
            self._button("Undo", discord.ButtonStyle.secondary, self._undo, row=1)
            self._button("Restart", discord.ButtonStyle.secondary, self._restart, row=1)

    def _button(self, label: str, style: discord.ButtonStyle, callback, row: int | None = None) -> None:
        button = discord.ui.Button(label=label, style=style, row=row)
        button.callback = callback
        self.add_item(button)

    def embed(self) -> discord.Embed:
        if self.outcome is not None:
            return discord.Embed(title="Game over", description=self.outcome, color=discord.Color.greyple())
        if self.guess is not None:
            conf = self.game.leader()[1] if self.game.leader() else 0.0
            return discord.Embed(
                title=f"Is it **{self.guess}**?",
                description=f"My confidence: {conf:.0%} · questions asked: {len(self.game.asked)}",
                color=discord.Color.blurple(),
            )
        number = len(self.game.asked) + 1
        return discord.Embed(
            title=self.eng.ATTRIBUTES[self.attr],
            description=f"Question {number} of {self.game.max_questions}. Answer honestly, and use Undo if you slip.",
            color=discord.Color.blurple(),
        )

    def _finish(self, text: str) -> None:
        self.outcome = text
        self.attr = self.guess = None
        self.clear_items()

    # ---------- handlers ----------

    def _make_answer(self, value: str):
        async def callback(interaction: discord.Interaction) -> None:
            if self.attr is None:
                return
            self.game.answer(self.attr, value)
            self._advance()
            await interaction.response.edit_message(embed=self.embed(), view=self if self.children else None)
        return callback

    async def _correct(self, interaction: discord.Interaction) -> None:
        self._finish(f"Got it! It was **{self.guess}**, found in {len(self.game.asked)} questions.")
        await interaction.response.edit_message(embed=self.embed(), view=None)

    async def _wrong(self, interaction: discord.Interaction) -> None:
        self.game.reject(self.guess)
        self._advance()
        await interaction.response.edit_message(embed=self.embed(), view=self if self.children else None)

    async def _undo(self, interaction: discord.Interaction) -> None:
        self.game.undo()
        self._advance()
        await interaction.response.edit_message(embed=self.embed(), view=self if self.children else None)

    async def _restart(self, interaction: discord.Interaction) -> None:
        self.game = self.eng.Game()
        self._advance()
        await interaction.response.edit_message(embed=self.embed(), view=self if self.children else None)


class Akinator(commands.Cog):
    @app_commands.command(name="akinator", description="Think of an animal, and I'll try to guess it in 20 questions.")
    async def akinator(self, interaction: discord.Interaction) -> None:
        session = Session(interaction.user.id)
        await interaction.response.send_message(embed=session.embed(), view=session)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Akinator())
