"""Loading and checking DISCORD_TOKEN. Nothing here prints or logs the token itself."""
from __future__ import annotations

import os
import re

ENV_NAME = "DISCORD_TOKEN"
PLACEHOLDER = "your-bot-token-here"
# A bot token is three base64url parts joined by dots: user id, timestamp, signature.
_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{20,}")
SETUP_HELP = (
    "Set it with:  python scripts/set_token.py   (input is hidden, saves to .env)\n"
    "On a host like Render, add DISCORD_TOKEN under the service's Environment settings instead.\n"
    "Get a token at https://discord.com/developers/applications -> your app -> Bot -> Reset Token."
)


class TokenError(ValueError):
    pass


def clean(raw: str | None) -> str:
    """Drop whitespace and quotes that often sneak in when pasting."""
    return (raw or "").strip().strip("\"'").strip()


def problem(token: str) -> str | None:
    """Why this token can't be right, or None if its shape looks fine."""
    if not token:
        return "DISCORD_TOKEN is not set."
    if token == PLACEHOLDER:
        return "DISCORD_TOKEN is still the placeholder from .env.example."
    if token.lower().startswith("bot "):
        return "DISCORD_TOKEN should be the token only, without 'Bot ' in front."
    if not _SHAPE.fullmatch(token):
        return "DISCORD_TOKEN doesn't look like a Discord bot token (expected three parts separated by dots)."
    return None


def describe(token: str) -> str:
    """Safe summary for logs: presence and length only."""
    return f"set ({len(token)} characters)" if token else "not set"


def load() -> str:
    """Read DISCORD_TOKEN from the environment (call load_dotenv() first). Raises TokenError with setup help."""
    token = clean(os.getenv(ENV_NAME))
    issue = problem(token)
    if issue:
        raise TokenError(f"{issue}\n{SETUP_HELP}")
    return token
