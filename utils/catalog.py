"""Generated catalog of configuration presets.

25 categories x 40 actions x 5 scopes x 10 strengths = 50,000 entries.

Nothing is built at startup. An entry is computed from its index when asked
for, and the full list is never held in memory. These are preset and setting
records. They are not 50,000 separately implemented features: only the
categories in utils/features.py have runtime behaviour.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple

CATEGORIES: tuple[str, ...] = (
    "moderation", "automod", "security", "antiraid", "verification", "leveling", "economy",
    "shop", "games", "trivia", "akinator", "anicatch", "tickets", "ai", "automation",
    "starboard", "welcome", "giveaways", "polls", "music", "backup", "server", "utility",
    "afk", "embeds",
)
ACTIONS: tuple[str, ...] = (
    "ban", "kick", "timeout", "warn", "purge", "lock", "slowmode", "tempban", "softban", "nick",
    "roleadd", "roleremove", "strike", "filter", "link", "invite", "caps", "emoji", "zalgo",
    "mentions", "duplicate", "raid", "nuke", "webhook", "botadd", "welcome", "reminder",
    "responder", "ticket", "transcript", "gamble", "slots", "trade", "catch", "battle", "pity",
    "summarize", "queue", "giveaway", "boost",
)
SCOPES: tuple[str, ...] = ("server", "category", "channel", "role", "member")
STRENGTHS: tuple[int, ...] = tuple(range(1, 11))

assert len(CATEGORIES) == 25 and len(set(CATEGORIES)) == 25
assert len(ACTIONS) == 40 and len(set(ACTIONS)) == 40

PER_CATEGORY = len(ACTIONS) * len(SCOPES) * len(STRENGTHS)  # 2,000
TOTAL = len(CATEGORIES) * PER_CATEGORY                       # 50,000

_CAT = {c: i for i, c in enumerate(CATEGORIES)}
_ACT = {a: i for i, a in enumerate(ACTIONS)}
_SCO = {s: i for i, s in enumerate(SCOPES)}


class Entry(NamedTuple):
    id: str
    category: str
    action: str
    scope: str
    strength: int


def _make(category: str, action: str, scope: str, strength: int) -> Entry:
    return Entry(f"{category}.{action}.{scope}.{strength}", category, action, scope, strength)


def get(index: int) -> Entry:
    """Entry at a catalog index, computed in O(1)."""
    if not 0 <= index < TOTAL:
        raise IndexError(index)
    rest, s = divmod(index, len(STRENGTHS))
    rest, sc = divmod(rest, len(SCOPES))
    c, a = divmod(rest, len(ACTIONS))
    return _make(CATEGORIES[c], ACTIONS[a], SCOPES[sc], STRENGTHS[s])


def lookup(feature_id: str) -> Entry | None:
    """Parse `category.action.scope.strength`. Returns None for anything else."""
    parts = feature_id.strip().lower().split(".")
    if len(parts) != 4:
        return None
    category, action, scope, raw = parts
    if category not in _CAT or action not in _ACT or scope not in _SCO:
        return None
    try:
        strength = int(raw)
    except ValueError:
        return None
    if not 1 <= strength <= len(STRENGTHS):
        return None
    return _make(category, action, scope, strength)


def iter_entries(category: str | None = None) -> Iterator[Entry]:
    """Lazily yield entries, optionally for one category."""
    start, stop = (0, TOTAL) if category is None else (_CAT[category] * PER_CATEGORY, (_CAT[category] + 1) * PER_CATEGORY)
    for i in range(start, stop):
        yield get(i)


def search(query: str, limit: int = 25) -> list[str]:
    """Up to `limit` ids containing `query`. Scans lazily and stops early.
    A query that starts with a category name only scans that category."""
    q = query.strip().lower()
    lo, hi = 0, TOTAL
    head = q.split(".", 1)[0]
    if head in _CAT:
        lo = _CAT[head] * PER_CATEGORY
        hi = lo + PER_CATEGORY
    out: list[str] = []
    for i in range(lo, hi):
        entry = get(i)
        if not q or q in entry.id:
            out.append(entry.id)
            if len(out) >= limit:
                break
    return out
