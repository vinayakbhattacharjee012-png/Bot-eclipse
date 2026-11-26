"""Set or check DISCORD_TOKEN without ever showing it.

    python scripts/set_token.py           paste a token (hidden), saved to .env with owner-only permissions
    python scripts/set_token.py --check   check the current token's format, then ask Discord which bot it belongs to
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiohttp  # installed with discord.py
from dotenv import load_dotenv

from utils import discord_token

ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def save(token: str, env_file: Path = ENV_FILE, example_file: Path = EXAMPLE_FILE) -> None:
    """Write DISCORD_TOKEN into env_file, keeping every other line. Starts from the example if env_file is new."""
    source = env_file if env_file.exists() else example_file
    lines = source.read_text(encoding="utf-8").splitlines() if source.exists() else []
    line = f"{discord_token.ENV_NAME}={token}"
    for i, existing in enumerate(lines):
        if existing.startswith(f"{discord_token.ENV_NAME}="):
            lines[i] = line
            break
    else:
        lines.append(line)
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(env_file, 0o600)  # also tighten a file that already existed


async def whoami(token: str) -> tuple[int, dict]:
    url = "https://discord.com/api/v10/users/@me"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
        url, headers={"Authorization": f"Bot {token}"}
    ) as resp:
        data = await resp.json(content_type=None) if resp.status == 200 else {}
        return resp.status, data


def check() -> int:
    from_env = discord_token.ENV_NAME in os.environ
    load_dotenv(ENV_FILE)
    token = discord_token.clean(os.getenv(discord_token.ENV_NAME))
    where = "environment variable" if from_env else ".env file"
    print(f"DISCORD_TOKEN: {discord_token.describe(token)}" + (f", from the {where}" if token else ""))
    issue = discord_token.problem(token)
    if issue:
        print(f"Problem: {issue}\n{discord_token.SETUP_HELP}")
        return 1
    print("Format: OK")
    try:
        status, data = asyncio.run(whoami(token))
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        print(f"Couldn't reach Discord to verify ({type(exc).__name__}). The format is fine; try again online.")
        return 2
    if status == 200:
        print(f"Discord accepted the token: bot {data.get('username')} (ID {data.get('id')}).")
        return 0
    if status == 401:
        print("Discord rejected this token. Reset it in the Developer Portal, then run: python scripts/set_token.py")
        return 1
    print(f"Couldn't verify: Discord answered HTTP {status}.")
    return 2


def prompt_and_save() -> int:
    token = discord_token.clean(getpass.getpass("Paste your bot token (hidden), then press Enter: "))
    issue = discord_token.problem(token)
    if issue:
        print(f"Not saved. {issue}")
        return 1
    save(token)
    print(f"Saved DISCORD_TOKEN to {ENV_FILE.name}: {discord_token.describe(token)}, owner-only permissions.")
    print("Next: python scripts/set_token.py --check")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Set or check DISCORD_TOKEN without displaying it.")
    parser.add_argument("--check", action="store_true", help="check the current token instead of setting one")
    args = parser.parse_args()
    sys.exit(check() if args.check else prompt_and_save())


if __name__ == "__main__":
    main()
