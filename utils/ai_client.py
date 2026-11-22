"""Client for a server-side AI endpoint that speaks the OpenAI chat-completions format.

Configure with environment variables (never in code):
  AI_BASE_URL  e.g. https://api.example.com/v1
  AI_API_KEY   secret, kept in the host's environment settings
  AI_MODEL     model name the endpoint expects

If any of them is missing, every call raises AIError with a setup message.
Nothing is faked. Error text never includes the key.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import aiohttp

SETUP_HELP = (
    "The AI assistant isn't set up on this server yet. The bot needs AI_BASE_URL, "
    "AI_API_KEY and AI_MODEL in its environment. Once they're set, restart the bot."
)
REQUEST_TIMEOUT = 45


class AIError(RuntimeError):
    pass


def settings() -> tuple[str, str, str] | None:
    base = os.getenv("AI_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    if not (base and key and model):
        return None
    return base, key, model


def configured() -> bool:
    return settings() is not None


def describe() -> str:
    cfg = settings()
    if cfg is None:
        return "not configured"
    return f"{urlparse(cfg[0]).netloc} · model `{cfg[2]}`"


async def chat(system: str, user: str, max_tokens: int = 600) -> str:
    cfg = settings()
    if cfg is None:
        raise AIError(SETUP_HELP)
    base, key, model = cfg
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {key}"}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            f"{base}/chat/completions", json=payload, headers=headers
        ) as resp:
            if resp.status != 200:
                raise AIError(f"The AI endpoint answered with HTTP {resp.status}.")
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as exc:
        raise AIError(f"Couldn't reach the AI endpoint ({type(exc).__name__}).") from exc
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("The AI endpoint sent a reply in an unexpected format.") from exc
