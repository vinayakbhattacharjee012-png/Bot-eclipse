"""Per-server module switches. utils/tree.py checks slash commands against
these, and event listeners call enabled() themselves."""
from __future__ import annotations

from utils import catalog
from utils.storage import store

# Qualified command name -> module category. A lookup tries the longest
# prefix first, so "eco shop_add" can belong to "shop" while "eco" is "economy".
# Commands not listed here (e.g. /feature, /help) are always on.
COMMAND_CATEGORY: dict[str, str] = {
    # Moderation and existing cogs
    "kick": "moderation", "ban": "moderation", "unban": "moderation", "timeout": "moderation",
    "untimeout": "moderation", "warn": "moderation", "warnings": "moderation",
    "clearwarnings": "moderation", "purge": "moderation", "lock": "moderation",
    "unlock": "moderation", "slowmode": "moderation", "setlogchannel": "moderation",
    "antispam": "moderation", "antiraid": "antiraid", "setupverification": "verification",
    "rank": "leveling", "leaderboard": "leveling", "setlevelchannel": "leveling",
    "setlevelrole": "leveling", "removelevelrole": "leveling", "setxp": "leveling",
    "ping": "utility", "announce": "utility", "reactionrole": "utility", "help": "utility",
    "avatar": "utility", "poll": "polls", "serverinfo": "server", "userinfo": "server",
    "afk": "afk",
    # New command groups
    "mod": "moderation", "automod": "automod", "security": "security",
    "eco": "economy", "eco shop_list": "shop", "eco shop_add": "shop", "eco shop_remove": "shop",
    "eco buy": "shop", "eco use": "shop", "eco inventory": "shop",
    "game": "games", "game trivia": "trivia",
    "akinator": "akinator", "anicatch": "anicatch", "ticket": "tickets", "ai": "ai",
    "automation": "automation", "automation starboard": "starboard",
    "automation welcome": "welcome", "automation goodbye": "welcome", "automation boost": "welcome",
    "automation embed": "embeds",
    "music": "music", "backup": "backup", "giveaway": "giveaways", "info": "server",
}

# Category -> registry handler that backs it (see utils/registry.py).
CATEGORY_HANDLER: dict[str, str] = {
    "ai": "ai", "akinator": "akinator", "anicatch": "anicatch", "automod": "automod", "music": "music",
}


def category_for(qualified_name: str) -> str | None:
    parts = qualified_name.split()
    while parts:
        key = " ".join(parts)
        if key in COMMAND_CATEGORY:
            return COMMAND_CATEGORY[key]
        parts.pop()
    return None


def _switches(guild_id: int) -> dict[str, bool]:
    return store.guild(guild_id).setdefault("features", {}).setdefault("categories", {})


def enabled(guild_id: int | None, category: str) -> bool:
    if guild_id is None:
        return True
    return bool(_switches(guild_id).get(category, True))


def set_enabled(guild_id: int, category: str, flag: bool) -> None:
    """Caller must `await store.save()` afterwards."""
    if category not in catalog.CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    _switches(guild_id)[category] = flag
