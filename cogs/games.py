"""Quick games: coin toss with streaks, dice, rock-paper-scissors, a number-guessing game,
trivia, and a leaderboard of wins. Games here are chance or trivia. None involve coins."""
from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import store

TRIVIA: tuple[tuple[str, str, tuple[str, str, str]], ...] = (
    ("What is the capital of France?", "Paris", ("Lyon", "Marseille", "Nice")),
    ("How many sides does a hexagon have?", "6", ("5", "7", "8")),
    ("Which planet is known as the Red Planet?", "Mars", ("Venus", "Jupiter", "Saturn")),
    ("What is 7 × 8?", "56", ("54", "48", "63")),
    ("What gas do plants take in for photosynthesis?", "Carbon dioxide", ("Oxygen", "Nitrogen", "Helium")),
    ("What is the chemical symbol for gold?", "Au", ("Ag", "Gd", "Go")),
    ("Who wrote 'Romeo and Juliet'?", "William Shakespeare", ("Charles Dickens", "Jane Austen", "Mark Twain")),
    ("Which is the largest ocean on Earth?", "Pacific Ocean", ("Atlantic Ocean", "Indian Ocean", "Arctic Ocean")),
    ("How many bones are in the adult human body?", "206", ("196", "212", "180")),
    ("In the common seven-continent model, how many continents are there?", "7", ("5", "6", "8")),
)
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
_RPS = [app_commands.Choice(name=c.title(), value=c) for c in BEATS]
_TOSS = [app_commands.Choice(name="heads", value="heads"), app_commands.Choice(name="tails", value="tails")]


def toss_results(rng: random.Random, n: int) -> list[str]:
    return [rng.choice(("heads", "tails")) for _ in range(n)]


def longest_streak(results: list[str], guess: str) -> int:
    best = current = 0
    for r in results:
        current = current + 1 if r == guess else 0
        best = max(best, current)
    return best


def rps_outcome(a: str, b: str) -> str:
    """Result from a's point of view: 'win', 'lose' or 'draw'."""
    if a == b:
        return "draw"
    return "win" if BEATS[a] == b else "lose"


def number_feedback(guess: int, secret: int) -> str:
    if guess == secret:
        return "correct"
    return "higher" if guess < secret else "lower"


def _wins(guild_id: int) -> dict[str, int]:
    return store.guild(guild_id).setdefault("games", {}).setdefault("wins", {})


async def _award(guild_id: int, user_id: int) -> None:
    wins = _wins(guild_id)
    wins[str(user_id)] = wins.get(str(user_id), 0) + 1
    await store.save()


class TriviaView(discord.ui.View):
    def __init__(self, owner_id: int, question: str, answer: str, options: list[str]) -> None:
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.question = question
        self.answer = answer
        self.answered = False
        for option in options:
            button = discord.ui.Button(label=option[:80], style=discord.ButtonStyle.primary)
            button.callback = self._make_callback(option)
            self.add_item(button)

    def _make_callback(self, option: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("Only the player who asked can answer this one.", ephemeral=True)
                return
            if self.answered:
                return
            self.answered = True
            self.stop()
            if option == self.answer:
                await _award(interaction.guild_id, interaction.user.id)
                text = f"✅ Correct! **{self.answer}**. You get a point."
            else:
                text = f"❌ Not quite. The answer was **{self.answer}**."
            await interaction.response.edit_message(content=f"**{self.question}**\n{text}", view=None)
        return callback


class Games(commands.Cog):
    game = app_commands.Group(name="game", description="Coin toss, dice, trivia, number games and a win leaderboard", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._numbers: dict[tuple[int, int], dict[str, int]] = {}

    @game.command(description="Flip a coin, or several. Optionally call heads or tails for a streak.")
    @app_commands.describe(count="How many flips (1 to 10)", call="Your call on every flip (optional)")
    @app_commands.choices(call=_TOSS)
    async def toss(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 10] = 1, call: app_commands.Choice[str] | None = None) -> None:
        results = toss_results(random.Random(), count)
        if count == 1:
            text = f"🪙 **{results[0].title()}**"
        else:
            tally = f"{results.count('heads')} heads, {results.count('tails')} tails"
            text = f"🪙 {' '.join(r[0].upper() for r in results)}\n{tally}"
        if call is not None:
            streak = longest_streak(results, call.value)
            text += f"\nYou called **{call.name}**. Longest run of right calls: **{streak}**."
        await interaction.response.send_message(text)

    @game.command(description="Roll dice.")
    @app_commands.describe(sides="Sides per die (2 to 100)", count="How many dice (1 to 10)")
    async def dice(self, interaction: discord.Interaction, sides: app_commands.Range[int, 2, 100] = 6, count: app_commands.Range[int, 1, 10] = 1) -> None:
        rolls = [random.randint(1, sides) for _ in range(count)]
        await interaction.response.send_message(f"🎲 {', '.join(map(str, rolls))} (total {sum(rolls)})")

    @game.command(description="Rock, paper, scissors against the bot.")
    @app_commands.describe(choice="Your move")
    @app_commands.choices(choice=_RPS)
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]) -> None:
        bot_move = random.choice(list(BEATS))
        outcome = rps_outcome(choice.value, bot_move)
        verdict = {"win": "You win!", "lose": "I win.", "draw": "Draw."}[outcome]
        await interaction.response.send_message(f"You: **{choice.value}** · Me: **{bot_move}**. {verdict}")

    @game.command(description="Guess my secret number from 1 to 100. You get 7 tries.")
    @app_commands.describe(guess="Your guess (1 to 100)")
    async def number(self, interaction: discord.Interaction, guess: app_commands.Range[int, 1, 100]) -> None:
        key = (interaction.guild_id, interaction.user.id)
        state = self._numbers.get(key)
        if state is None:
            state = {"secret": random.randint(1, 100), "left": 7}
            self._numbers[key] = state
        state["left"] -= 1
        feedback = number_feedback(guess, state["secret"])
        if feedback == "correct":
            used = 7 - state["left"]
            del self._numbers[key]
            await _award(interaction.guild_id, interaction.user.id)
            await interaction.response.send_message(f"🎯 **{guess}** is right. Solved in {used} tr{'y' if used == 1 else 'ies'}. +1 win.")
        elif state["left"] == 0:
            secret = state["secret"]
            del self._numbers[key]
            await interaction.response.send_message(f"Out of tries. The number was **{secret}**.")
        else:
            await interaction.response.send_message(f"Go **{feedback}** than {guess}. {state['left']} tries left.")

    @game.command(description="Answer a trivia question. Right answers earn a win point.")
    async def trivia(self, interaction: discord.Interaction) -> None:
        question, answer, distractors = random.choice(TRIVIA)
        options = [answer, *distractors]
        random.shuffle(options)
        view = TriviaView(interaction.user.id, question, answer, options)
        await interaction.response.send_message(f"**{question}**", view=view)

    @game.command(description="Who has the most game wins here.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = sorted(_wins(interaction.guild_id).items(), key=lambda kv: kv[1], reverse=True)[:10]
        if not rows:
            await interaction.response.send_message("No wins yet. Try `/game trivia`.", ephemeral=True)
            return
        lines = []
        for i, (uid, wins) in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"`#{i}` **{name}** — {wins} win{'s' if wins != 1 else ''}")
        await interaction.response.send_message(embed=discord.Embed(title="Game wins", description="\n".join(lines), color=discord.Color.blurple()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))
