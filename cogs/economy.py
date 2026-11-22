"""Virtual economy: coins, daily and work rewards, pay, rob, gamble, slots, a server shop,
inventories, item use and item trades. Coins are virtual and have no cash value."""
from __future__ import annotations

import random
import time
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from utils.confirm import ConfirmView
from utils.cooldowns import remaining
from utils.storage import store

CURRENCY = "coins"
DAILY_REWARD = 200
DAILY_COOLDOWN = 24 * 3600
WORK_COOLDOWN = 3600
ROB_COOLDOWN = 4 * 3600
ROB_MIN_TARGET = 100
ROB_SUCCESS_CHANCE = 0.4
ROB_FINE_CAP = 50
GAMBLE_WIN_CHANCE = 0.45
# (symbol, weight). Three matching returns 6x the bet. Two matching returns the bet.
# Expected return is about 0.93 of the stake, so the house keeps a small edge.
REELS: tuple[tuple[str, int], ...] = (("🍒", 5), ("🍋", 4), ("🔔", 3), ("⭐", 2), ("7️⃣", 1))
SLOT_JACKPOT_RETURN = 6
SLOT_PAIR_RETURN = 1
SHOP_KINDS = ("role", "consumable")
_RNG = random.Random()


def spin(rng: random.Random) -> tuple[str, str, str]:
    symbols = [s for s, _ in REELS]
    weights = [w for _, w in REELS]
    return tuple(rng.choices(symbols, weights, k=3))  # type: ignore[return-value]


def slot_return(reels: tuple[str, ...]) -> int:
    """Multiple of the bet returned. 0 means the bet is lost."""
    most = max(Counter(reels).values())
    if most == 3:
        return SLOT_JACKPOT_RETURN
    if most == 2:
        return SLOT_PAIR_RETURN
    return 0


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _sec(guild_id: int) -> dict:
    sec = store.guild(guild_id).setdefault("economy", {})
    for key in ("balances", "last", "shop", "inventory"):
        sec.setdefault(key, {})
    return sec


def _bal(sec: dict, user_id: int) -> int:
    return int(sec["balances"].get(str(user_id), 0))


def _add(sec: dict, user_id: int, amount: int) -> None:
    sec["balances"][str(user_id)] = _bal(sec, user_id) + amount


def _item_id(name: str) -> str:
    return "-".join(name.lower().split())[:32]


async def _item_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    sec = _sec(interaction.guild_id)
    cur = current.lower()
    return [
        app_commands.Choice(name=item["name"], value=item["name"])
        for item in sec["shop"].values()
        if cur in item["name"].lower()
    ][:25]


async def _owned_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    sec = _sec(interaction.guild_id)
    owned = sec["inventory"].get(str(interaction.user.id), {})
    cur = current.lower()
    out = []
    for item_id, count in owned.items():
        item = sec["shop"].get(item_id)
        if count > 0 and item and cur in item["name"].lower():
            out.append(app_commands.Choice(name=f"{item['name']} (x{count})", value=item["name"]))
    return out[:25]


class Economy(commands.Cog):
    eco = app_commands.Group(name="eco", description="Coins, rewards, games of chance, shop and trades", guild_only=True)

    @eco.command(description="Check your coins, or someone else's.")
    @app_commands.describe(member="Whose balance to check")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        sec = _sec(interaction.guild_id)
        await interaction.response.send_message(f"**{member.display_name}** has **{_bal(sec, member.id):,}** {CURRENCY}.")

    @eco.command(description=f"Claim your daily {DAILY_REWARD} coins (once every 24 hours).")
    async def daily(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        now = time.time()
        key = f"daily:{interaction.user.id}"
        wait = remaining(sec["last"].get(key, 0), DAILY_COOLDOWN, now)
        if wait:
            await interaction.response.send_message(f"Already claimed. Come back in **{format_duration(wait)}**.", ephemeral=True)
            return
        _add(sec, interaction.user.id, DAILY_REWARD)
        sec["last"][key] = now
        await store.save()
        await interaction.response.send_message(f"You claimed **{DAILY_REWARD}** {CURRENCY}. Balance: **{_bal(sec, interaction.user.id):,}**.")

    @eco.command(description="Work a shift for coins (once an hour).")
    async def work(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        now = time.time()
        key = f"work:{interaction.user.id}"
        wait = remaining(sec["last"].get(key, 0), WORK_COOLDOWN, now)
        if wait:
            await interaction.response.send_message(f"You're still tired. Work again in **{format_duration(wait)}**.", ephemeral=True)
            return
        earned = random.randint(20, 120)
        _add(sec, interaction.user.id, earned)
        sec["last"][key] = now
        await store.save()
        await interaction.response.send_message(f"Shift done. You earned **{earned}** {CURRENCY}.")

    @eco.command(description="Send coins to another member.")
    @app_commands.describe(member="Who to pay", amount="How many coins")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("Pick a real person who isn't you.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        if _bal(sec, interaction.user.id) < amount:
            await interaction.response.send_message(f"You only have **{_bal(sec, interaction.user.id):,}** {CURRENCY}.", ephemeral=True)
            return
        _add(sec, interaction.user.id, -amount)
        _add(sec, member.id, amount)
        await store.save()
        await interaction.response.send_message(f"Sent **{amount:,}** {CURRENCY} to **{member.display_name}**.")

    @eco.command(description="Try to steal coins from someone (risky, with a cooldown).")
    @app_commands.describe(member="Who to rob")
    async def rob(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("You can't rob that person.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        now = time.time()
        key = f"rob:{interaction.user.id}"
        wait = remaining(sec["last"].get(key, 0), ROB_COOLDOWN, now)
        if wait:
            await interaction.response.send_message(f"Lying low. Try again in **{format_duration(wait)}**.", ephemeral=True)
            return
        target_bal = _bal(sec, member.id)
        if target_bal < ROB_MIN_TARGET:
            await interaction.response.send_message(f"**{member.display_name}** has too little to be worth it.", ephemeral=True)
            return
        sec["last"][key] = now
        if random.random() < ROB_SUCCESS_CHANCE:
            stolen = min(target_bal, max(1, int(target_bal * random.uniform(0.1, 0.3))))
            _add(sec, member.id, -stolen)
            _add(sec, interaction.user.id, stolen)
            text = f"It worked. You took **{stolen:,}** {CURRENCY} from **{member.display_name}**."
        else:
            fine = min(_bal(sec, interaction.user.id), ROB_FINE_CAP)
            _add(sec, interaction.user.id, -fine)
            _add(sec, member.id, fine)
            text = f"Caught. You paid **{member.display_name}** a fine of **{fine:,}** {CURRENCY}."
        await store.save()
        await interaction.response.send_message(text)

    @eco.command(description="Bet coins on a coin flip with a small house edge.")
    @app_commands.describe(amount="How many coins to bet")
    async def gamble(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100_000]) -> None:
        sec = _sec(interaction.guild_id)
        if _bal(sec, interaction.user.id) < amount:
            await interaction.response.send_message(f"You only have **{_bal(sec, interaction.user.id):,}** {CURRENCY}.", ephemeral=True)
            return
        if random.random() < GAMBLE_WIN_CHANCE:
            _add(sec, interaction.user.id, amount)
            text = f"You won **{amount:,}** {CURRENCY}!"
        else:
            _add(sec, interaction.user.id, -amount)
            text = f"You lost **{amount:,}** {CURRENCY}."
        await store.save()
        await interaction.response.send_message(f"{text} Balance: **{_bal(sec, interaction.user.id):,}**.")

    @eco.command(description="Pull the slot machine. Three matching pays 6x the bet.")
    @app_commands.describe(bet="How many coins to bet")
    async def slots(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1, 100_000]) -> None:
        sec = _sec(interaction.guild_id)
        if _bal(sec, interaction.user.id) < bet:
            await interaction.response.send_message(f"You only have **{_bal(sec, interaction.user.id):,}** {CURRENCY}.", ephemeral=True)
            return
        reels = spin(_RNG)
        multiple = slot_return(reels)
        net = bet * (multiple - 1)
        _add(sec, interaction.user.id, net)
        await store.save()
        result = {SLOT_JACKPOT_RETURN: "Jackpot!", SLOT_PAIR_RETURN: "Pair, bet returned.", 0: "No match."}[multiple]
        sign = f"+{net:,}" if net > 0 else f"{net:,}"
        await interaction.response.send_message(
            f"🎰 {' | '.join(reels)}\n{result} ({sign} {CURRENCY}). Balance: **{_bal(sec, interaction.user.id):,}**."
        )

    # ---------- shop ----------

    @eco.command(name="shop_list", description="Show the server shop.")
    async def shop_list(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        items = sorted(sec["shop"].values(), key=lambda i: i["name"].lower())
        if not items:
            await interaction.response.send_message("The shop is empty. Admins can add items with `/eco shop_add`.", ephemeral=True)
            return
        lines = [
            f"**{i['name']}** — {i['price']:,} {CURRENCY} · {i['kind']}" + (f" · {i['description']}" if i.get("description") else "")
            for i in items
        ]
        embed = discord.Embed(title="Server shop", description="\n".join(lines)[:4000], color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    @eco.command(name="shop_add", description="Admin: add an item to the shop.")
    @app_commands.describe(
        name="Item name (up to 32 characters)", price="Price in coins", kind="role gives a role when used; consumable is used up",
        role="The role to give (required for role items)", description="Short description (optional)",
    )
    @app_commands.choices(kind=[app_commands.Choice(name=k, value=k) for k in SHOP_KINDS])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shop_add(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 32], price: app_commands.Range[int, 1, 1_000_000],
        kind: app_commands.Choice[str], role: discord.Role | None = None, description: app_commands.Range[str, 0, 100] = "",
    ) -> None:
        item_id = _item_id(name)
        if not item_id:
            await interaction.response.send_message("That name doesn't work. Use some letters or numbers.", ephemeral=True)
            return
        if kind.value == "role" and role is None:
            await interaction.response.send_message("Role items need a `role`.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        sec["shop"][item_id] = {
            "name": name.strip(), "price": price, "kind": kind.value,
            "role_id": role.id if role else None, "description": description.strip(),
        }
        await store.save()
        await interaction.response.send_message(f"Added **{name.strip()}** to the shop for {price:,} {CURRENCY}.", ephemeral=True)

    @eco.command(name="shop_remove", description="Admin: remove an item from the shop.")
    @app_commands.describe(item="The item to remove")
    @app_commands.autocomplete(item=_item_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def shop_remove(self, interaction: discord.Interaction, item: str) -> None:
        sec = _sec(interaction.guild_id)
        removed = sec["shop"].pop(_item_id(item), None)
        await store.save()
        if removed:
            await interaction.response.send_message(f"Removed **{removed['name']}** from the shop.", ephemeral=True)
        else:
            await interaction.response.send_message("No shop item with that name.", ephemeral=True)

    @eco.command(description="Buy one of a shop item.")
    @app_commands.describe(item="The item to buy")
    @app_commands.autocomplete(item=_item_choices)
    async def buy(self, interaction: discord.Interaction, item: str) -> None:
        sec = _sec(interaction.guild_id)
        item_id = _item_id(item)
        entry = sec["shop"].get(item_id)
        if entry is None:
            await interaction.response.send_message("No shop item with that name.", ephemeral=True)
            return
        if _bal(sec, interaction.user.id) < entry["price"]:
            await interaction.response.send_message(f"That costs {entry['price']:,} {CURRENCY}. You don't have enough.", ephemeral=True)
            return
        _add(sec, interaction.user.id, -entry["price"])
        owned = sec["inventory"].setdefault(str(interaction.user.id), {})
        owned[item_id] = owned.get(item_id, 0) + 1
        await store.save()
        await interaction.response.send_message(f"Bought **{entry['name']}**. Use it with `/eco use`.", ephemeral=True)

    @eco.command(description="See what you own.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        owned = {k: v for k, v in sec["inventory"].get(str(interaction.user.id), {}).items() if v > 0}
        if not owned:
            await interaction.response.send_message("Your inventory is empty.", ephemeral=True)
            return
        lines = [f"**{sec['shop'][k]['name']}** × {v}" for k, v in owned.items() if k in sec["shop"]]
        await interaction.response.send_message("\n".join(lines) or "Your items are no longer sold here.", ephemeral=True)

    @eco.command(description="Use one of your items. Role items give you the role.")
    @app_commands.describe(item="The item to use")
    @app_commands.autocomplete(item=_owned_choices)
    async def use(self, interaction: discord.Interaction, item: str) -> None:
        sec = _sec(interaction.guild_id)
        item_id = _item_id(item)
        owned = sec["inventory"].get(str(interaction.user.id), {})
        entry = sec["shop"].get(item_id)
        if entry is None or owned.get(item_id, 0) < 1:
            await interaction.response.send_message("You don't own that item.", ephemeral=True)
            return
        if entry["kind"] == "role":
            role = interaction.guild.get_role(entry["role_id"]) if entry.get("role_id") else None
            if role is None:
                await interaction.response.send_message("That item's role no longer exists. Ask an admin.", ephemeral=True)
                return
            try:
                await interaction.user.add_roles(role, reason=f"Used shop item {entry['name']}")
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to give that role.", ephemeral=True)
                return
            text = f"You now have the **{role.name}** role from **{entry['name']}**."
        else:
            text = f"You used **{entry['name']}**."
        owned[item_id] -= 1
        await store.save()
        await interaction.response.send_message(text, ephemeral=True)

    @eco.command(description="Offer one of your items to someone for coins. They must accept.")
    @app_commands.describe(member="Who to trade with", item="Your item to offer", price="Coins you want in return")
    @app_commands.autocomplete(item=_owned_choices)
    async def trade(self, interaction: discord.Interaction, member: discord.Member, item: str, price: app_commands.Range[int, 0, 1_000_000]) -> None:
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("Pick someone else to trade with.", ephemeral=True)
            return
        sec = _sec(interaction.guild_id)
        item_id = _item_id(item)
        if sec["inventory"].get(str(interaction.user.id), {}).get(item_id, 0) < 1 or item_id not in sec["shop"]:
            await interaction.response.send_message("You don't own that item.", ephemeral=True)
            return
        name = sec["shop"][item_id]["name"]
        view = ConfirmView(owner_id=member.id, timeout=120)
        await interaction.response.send_message(
            f"{member.mention}, **{interaction.user.display_name}** offers **{name}** for **{price:,}** {CURRENCY}. Accept?",
            view=view,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        await view.wait()
        if view.value is None:
            await interaction.followup.send("The trade expired.")
            return
        if not view.value:
            await interaction.followup.send("The trade was declined.")
            return
        # Re-check both sides: things may have changed while the offer was open.
        owned = sec["inventory"].get(str(interaction.user.id), {})
        if owned.get(item_id, 0) < 1 or _bal(sec, member.id) < price:
            await interaction.followup.send("The trade can't go through any more. Someone no longer has what it needs.")
            return
        owned[item_id] -= 1
        theirs = sec["inventory"].setdefault(str(member.id), {})
        theirs[item_id] = theirs.get(item_id, 0) + 1
        _add(sec, member.id, -price)
        _add(sec, interaction.user.id, price)
        await store.save()
        await interaction.followup.send(f"Trade done: **{name}** went to {member.mention} for **{price:,}** {CURRENCY}.", allowed_mentions=discord.AllowedMentions(users=[member]))

    @eco.command(description="The richest members here.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        sec = _sec(interaction.guild_id)
        rows = sorted(sec["balances"].items(), key=lambda kv: kv[1], reverse=True)[:10]
        rows = [(uid, bal) for uid, bal in rows if bal > 0]
        if not rows:
            await interaction.response.send_message("Nobody has any coins yet.", ephemeral=True)
            return
        lines = []
        for i, (uid, bal) in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"`#{i}` **{name}** — {bal:,} {CURRENCY}")
        embed = discord.Embed(title=f"{interaction.guild.name} · richest", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy())
