"""AniCatch mechanics: spawn odds, catch odds with pity, and battle power. Pure logic.

The creatures are original names made up for this bot.
"""
from __future__ import annotations

import random
from collections import Counter

# (name, rarity, power)
CREATURES: tuple[tuple[str, str, int], ...] = (
    ("Emberfox", "common", 12), ("Tidewisp", "common", 11), ("Stonepup", "common", 10), ("Mossling", "common", 10),
    ("Gale Hawk", "uncommon", 18), ("Coralune", "uncommon", 17), ("Duskmoth", "uncommon", 16),
    ("Thornwyrm", "rare", 26), ("Glacimane", "rare", 28),
    ("Aurora Drake", "epic", 40), ("Voidkoi", "epic", 38),
    ("Sunseraph", "legendary", 60),
)
RARITY_WEIGHT = {"common": 60, "uncommon": 25, "rare": 10, "epic": 4, "legendary": 1}
CATCH_CHANCE = {"common": 0.6, "uncommon": 0.4, "rare": 0.2, "epic": 0.1, "legendary": 0.03}
PITY_MISSES = 8          # after this many misses in a row, the next catch is guaranteed
SPAWN_EVERY_MESSAGES = 40
SPAWN_MIN_GAP = 60       # seconds between spawns in one channel
SPAWN_TTL = 120          # seconds a spawn stays catchable

_BY_NAME = {name: (rarity, power) for name, rarity, power in CREATURES}


def rarity_of(name: str) -> str:
    return _BY_NAME[name][0]


def power_of(name: str) -> int:
    return _BY_NAME[name][1]


_TIER_SIZE = Counter(rarity for _, rarity, _ in CREATURES)


def roll_spawn(rng: random.Random) -> str:
    """RARITY_WEIGHT is the share of each tier, split evenly across its creatures."""
    names = [c[0] for c in CREATURES]
    weights = [RARITY_WEIGHT[c[1]] / _TIER_SIZE[c[1]] for c in CREATURES]
    return rng.choices(names, weights)[0]


def attempt_catch(rng: random.Random, name: str, misses: int) -> bool:
    if misses >= PITY_MISSES:
        return True
    return rng.random() < CATCH_CHANCE[rarity_of(name)]


def battle_power(counts: dict[str, int], rng: random.Random) -> int:
    """Best three caught creatures, plus up to 20% random variance."""
    powers = sorted((power_of(n) for n, c in counts.items() if c > 0), reverse=True)[:3]
    base = sum(powers)
    if base == 0:
        return 0
    return base + rng.randint(0, base // 5)
