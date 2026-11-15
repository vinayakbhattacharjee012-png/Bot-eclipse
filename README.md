# Discord Bot

A moderation, leveling and utility bot built with [discord.py](https://discordpy.readthedocs.io/) 2.x and slash commands.

## Features

**Moderation & security**
- `/kick`, `/ban`, `/unban`, `/timeout`, `/untimeout`
- `/warn`, `/warnings`, `/clearwarnings` — persistent warning log
- `/purge`, `/lock`, `/unlock`, `/slowmode`
- `/setlogchannel` — where mod actions get logged
- **Automatic anti-spam**: times out and cleans up anyone sending messages too fast. Tune with `/antispam`.
- **Automatic anti-raid**: detects a burst of joins and can auto-kick very-new accounts while a raid is active. Tune with `/antiraid`.

**Leveling & engagement**
- Chat to earn XP (60s cooldown so spamming doesn't help) and level up
- `/rank`, `/leaderboard`
- `/setlevelchannel`, `/setlevelrole`, `/removelevelrole`, `/setxp`

**Utility**
- `/ping`, `/serverinfo`, `/userinfo`, `/avatar`
- `/poll`, `/announce`, `/reactionrole`
- `/help`

**Verification**
- `/setupverification` posts a button — clicking it gives a role. Works across restarts.

**AFK**
- `/afk [reason]` — clears automatically when you post again, and tells anyone who @-mentions you that you're away.

All settings are per-server and saved to `data/store.json`, so they survive restarts.

## Setup

1. **Create the bot application:**
   - Go to https://discord.com/developers/applications → **New Application**.
   - Under **Bot**, click **Reset Token** and copy it — you won't be able to see it again.
   - Under **Bot → Privileged Gateway Intents**, turn on **Server Members Intent** and **Message Content Intent**. The bot won't start without these (leveling needs message content, verification/anti-raid need the members intent).
   - Under **OAuth2 → URL Generator**, check `bot` and `applications.commands` scopes, then under **Bot Permissions** check at least: Kick Members, Ban Members, Moderate Members, Manage Roles, Manage Channels, Manage Messages, Read Message History, Send Messages, Add Reactions. Open the generated URL to invite the bot to your server.

2. **Install dependencies:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and paste in your bot token. While testing, also set `DEV_GUILD_ID` to your server's ID (enable Developer Mode in Discord settings, then right-click your server icon → Copy Server ID) — this makes slash commands appear instantly in that one server instead of waiting up to an hour for a global sync.

4. **Run it:**
   ```bash
   python bot.py
   ```
   You should see `Logged in as YourBot#1234` in the console, and the slash commands will appear in Discord.

## First steps in your server

Run these once, as a server admin:
- `/setlogchannel #mod-log` — moderation and anti-raid/anti-spam events get posted there.
- `/setupverification role:@Verified` — posts the verify button. Make sure the bot's role is above `@Verified` in **Server Settings → Roles**.
- `/setlevelchannel #level-ups` (optional) — otherwise level-ups announce in whatever channel triggered them.

## Deploying it live (Render, free tier)

Render's **Background Worker** type has no free tier (bots run continuously, so Render only offers workers on paid plans, ~$7/mo+). To run this for **$0**, it deploys as a free **Web Service** instead: `utils/keepalive.py` runs a tiny HTTP server (`/` and `/health`) alongside the real Discord connection in the same process, just so Render has something to check. The Discord bot itself doesn't use HTTP — this is purely to satisfy Render's free-tier requirement.

1. Push this project to its own GitHub repo (already done if you're reading this from one).
2. In Render, **New → Web Service** (not Background Worker).
3. Connect the repo. Build command: `pip install -r requirements.txt`. Start command: `python bot.py`.
4. Add `DISCORD_TOKEN` (and optionally `OWNER_LOG_CHANNEL_ID`) under **Environment** — never commit your real `.env` file. Leave `PORT` alone; Render sets it automatically.
5. Deploy. Check the Render logs for `Logged in as ...` to confirm it's online. Opening the service's `.onrender.com` URL should show `{"status": "online", ...}`.
6. **Add it to UptimeRobot** (same pattern you already use for your other Render projects): monitor the `.onrender.com` URL every 5 minutes. Free Render web services spin down after ~15 minutes idle; the ping keeps it awake. Without this, the bot will go offline after sitting unused.

If you'd rather pay for a proper Background Worker instead (no keep-alive trick needed), use `python bot.py` as the start command there too — `run_keepalive_server` only binds a port if `PORT` is set, so it's harmless either way.

**Important:** `data/store.json` lives on local disk. Render's free/background-worker disks are **not persistent across deploys** — a redeploy wipes it, resetting levels/warnings/config. For anything you want to survive redeploys long-term, either upgrade to a Render instance with a persistent disk, or swap `utils/storage.py` for a small hosted database later (the storage API is small and isolated specifically so that swap is easy).

## Project layout

```
bot.py                 entry point, loads cogs, syncs slash commands
cogs/
  moderation.py         kick/ban/timeout/warn/purge/lock + anti-spam
  antiraid.py            join-rate raid detection + auto-kick
  leveling.py            XP, levels, leaderboard, level roles
  verification.py        button-based verification
  afk.py                 AFK tracking
  utility.py             info commands, polls, announcements, reaction roles, help
utils/
  storage.py             tiny JSON data store (atomic writes, async-safe)
  keepalive.py           HTTP health server for Render's free Web Service tier
data/store.json          created automatically on first run
```

## Extending it

Each file in `cogs/` is self-contained — add a new file there and list it in `COGS` in `bot.py` to add a new feature area without touching existing code.
