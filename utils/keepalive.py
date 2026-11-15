"""A tiny HTTP server so this bot can run on Render's FREE Web Service tier
instead of a paid Background Worker.

Render's free tier only exists for services that listen on $PORT and answer
HTTP requests -- a plain background process isn't eligible. This just gives
Render (and a pinger like UptimeRobot) something to check, and that ping is
what keeps a free Render web service from spinning down.

This does not affect the bot itself: the Discord gateway connection runs
independently in the same process, started alongside this server in
bot.py's main().
"""
from __future__ import annotations

import logging
import os

from aiohttp import web

log = logging.getLogger("keepalive")


def build_app(bot) -> web.Application:
    async def health(request: web.Request) -> web.Response:
        online = bot.is_ready() and not bot.is_closed()
        status = 200 if online else 503
        body = {
            "status": "online" if online else "starting",
            "bot": str(bot.user) if bot.user else None,
            "guilds": len(bot.guilds) if online else 0,
            "latency_ms": round(bot.latency * 1000) if online else None,
        }
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    return app


async def run_keepalive_server(bot) -> None:
    port = int(os.environ.get("PORT", 8080))
    app = build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Keep-alive HTTP server listening on 0.0.0.0:%d (/ and /health)", port)
