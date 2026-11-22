"""Automod detectors. Pure functions with no Discord objects, so they are easy to test."""
from __future__ import annotations

import re
import unicodedata
from collections import deque
from collections.abc import Iterable
from functools import lru_cache

INVITE_RE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]+)", re.IGNORECASE)
LINK_HOST_RE = re.compile(r"https?://([^/\s:?#]+)", re.IGNORECASE)
MENTION_RE = re.compile(r"<@[!&]?\d+>")
EMOJI_RE = re.compile(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF☀-➿]")

DEFAULT_RULES: dict[str, bool] = {
    "invites": True, "links": False, "mentions": True, "caps": True,
    "zalgo": True, "emoji": True, "words": True, "duplicates": True,
}
RULE_LABELS: dict[str, str] = {
    "invites": "invite link", "links": "blocked link", "mentions": "mass mention",
    "caps": "caps lock", "zalgo": "zalgo text", "emoji": "emoji spam",
    "words": "blocked word", "duplicates": "duplicate message",
}


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def has_invite(text: str, allowed_codes: Iterable[str] = ()) -> bool:
    allowed = set(allowed_codes)
    return any(code not in allowed for code in INVITE_RE.findall(text))


def has_blocked_link(text: str, domains: Iterable[str]) -> bool:
    blocked = [d.lower() for d in domains]
    if not blocked:
        return False
    for host in LINK_HOST_RE.findall(text):
        host = host.lower()
        if any(host == d or host.endswith("." + d) for d in blocked):
            return True
    return False


def mention_count(text: str) -> int:
    return len(MENTION_RE.findall(text))


def emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text))


def is_caps(text: str, min_letters: int = 12, ratio: float = 0.8) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < min_letters:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= ratio


def is_zalgo(text: str, threshold: int = 10) -> bool:
    return sum(1 for c in text if unicodedata.category(c) == "Mn") >= threshold


@lru_cache(maxsize=64)
def _word_pattern(words: tuple[str, ...]) -> re.Pattern[str] | None:
    if not words:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


def has_blocked_word(text: str, words: Iterable[str]) -> bool:
    pattern = _word_pattern(tuple(sorted({w.strip().lower() for w in words if w.strip()})))
    return bool(pattern and pattern.search(text))


def is_duplicate(history: deque, text: str, now: float, window: float, count: int) -> bool:
    """`history` holds (normalized text, timestamp) pairs. Records this message and
    reports whether it is the `count`th copy (or later) inside the window."""
    while history and now - history[0][1] > window:
        history.popleft()
    same = sum(1 for t, _ in history if t == text)
    history.append((text, now))
    return same + 1 >= count


def check_message(text: str, cfg: dict, dup_history: deque, now: float) -> list[str]:
    """Returns the labels of every rule the message breaks (empty = clean)."""
    rules = {**DEFAULT_RULES, **cfg.get("rules", {})}
    norm = normalize(text)
    dup = bool(norm) and is_duplicate(dup_history, norm, now, cfg.get("dup_window", 20), cfg.get("dup_count", 3))
    hits: list[str] = []
    if rules["invites"] and has_invite(text, cfg.get("allowed_invites", ())):
        hits.append("invites")
    if rules["links"] and has_blocked_link(text, cfg.get("domains", ())):
        hits.append("links")
    if rules["mentions"] and mention_count(text) >= cfg.get("max_mentions", 5):
        hits.append("mentions")
    if rules["caps"] and is_caps(text):
        hits.append("caps")
    if rules["zalgo"] and is_zalgo(text):
        hits.append("zalgo")
    if rules["emoji"] and emoji_count(text) >= cfg.get("max_emoji", 12):
        hits.append("emoji")
    if rules["words"] and has_blocked_word(text, cfg.get("words", ())):
        hits.append("words")
    if rules["duplicates"] and dup:
        hits.append("duplicates")
    return [RULE_LABELS[h] for h in hits]
