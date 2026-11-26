"""Verification suite for the Eclipse modules. Run from the project root:

    python -m unittest discover -s tests -v

Nothing here connects to Discord or writes to data/store.json. The AI client test starts a
small local HTTP server on 127.0.0.1 and uses a throwaway key.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from discord import app_commands

from utils import (
    ai_client,
    akinator_engine,
    anicatch_engine,
    automod_rules,
    catalog,
    cooldowns,
    features,
    music_queue,
    registry,
)
from utils.tree import EclipseTree


class CatalogTests(unittest.TestCase):
    def test_size_is_fifty_thousand(self):
        self.assertEqual(catalog.TOTAL, 50_000)
        self.assertEqual(len(catalog.CATEGORIES), 25)
        self.assertEqual(len(catalog.ACTIONS), 40)

    def test_index_round_trips_through_lookup(self):
        for index in (0, 1, 9, 10, 1999, 2000, 25_000, 49_999):
            entry = catalog.get(index)
            self.assertEqual(catalog.lookup(entry.id), entry)

    def test_invalid_ids_are_rejected(self):
        self.assertIsNone(catalog.lookup("moderation.ban.server.11"))
        self.assertIsNone(catalog.lookup("moderation.ban.server"))
        self.assertIsNone(catalog.lookup("nope.ban.server.1"))
        self.assertIsNone(catalog.lookup("moderation.nope.server.1"))
        with self.assertRaises(IndexError):
            catalog.get(catalog.TOTAL)

    def test_search_is_capped_and_narrowed_by_category(self):
        hits = catalog.search("ban", limit=25)
        self.assertEqual(len(hits), 25)
        only_economy = catalog.search("economy.gamble", limit=25)
        self.assertTrue(only_economy)
        self.assertTrue(all(h.startswith("economy.gamble") for h in only_economy))

    def test_choice_limit_fits_discord(self):
        self.assertLessEqual(len(catalog.CATEGORIES), 25)


class RegistryTests(unittest.TestCase):
    def test_handlers_import_on_demand(self):
        module = registry.get("akinator")
        self.assertEqual(module.__name__, "utils.akinator_engine")
        self.assertIn("akinator", registry.loaded())
        with self.assertRaises(KeyError):
            registry.get("does-not-exist")


class FeatureSwitchTests(unittest.TestCase):
    def test_longest_prefix_wins(self):
        self.assertEqual(features.category_for("eco shop_add"), "shop")
        self.assertEqual(features.category_for("eco balance"), "economy")
        self.assertEqual(features.category_for("game trivia"), "trivia")
        self.assertEqual(features.category_for("game dice"), "games")
        self.assertIsNone(features.category_for("feature list"))

    def test_switch_defaults_on_and_can_be_flipped(self):
        gid = 987654321
        self.assertTrue(features.enabled(gid, "economy"))
        features.set_enabled(gid, "economy", False)
        self.assertFalse(features.enabled(gid, "economy"))
        features.set_enabled(gid, "economy", True)
        self.assertTrue(features.enabled(gid, "economy"))
        with self.assertRaises(ValueError):
            features.set_enabled(gid, "not-a-category", False)

    def test_every_mapped_category_is_a_real_category(self):
        for category in set(features.COMMAND_CATEGORY.values()):
            self.assertIn(category, catalog.CATEGORIES)


class CooldownTests(unittest.TestCase):
    def test_bucket_limits_then_recovers(self):
        bucket = cooldowns.Bucket(limit=2, per=10)
        self.assertEqual(bucket.hit("u", 0), 0.0)
        self.assertEqual(bucket.hit("u", 1), 0.0)
        self.assertAlmostEqual(bucket.hit("u", 2), 8.0)
        self.assertEqual(bucket.hit("u", 11), 0.0)

    def test_sliding_counter_forgets_old_events(self):
        counter = cooldowns.SlidingCounter()
        self.assertEqual(counter.add("k", 10, now=0), 1)
        self.assertEqual(counter.add("k", 10, now=5), 2)
        self.assertEqual(counter.add("k", 10, now=12), 2)  # the event at t=0 has expired

    def test_remaining(self):
        self.assertEqual(cooldowns.remaining(100, 60, 120), 40)
        self.assertEqual(cooldowns.remaining(100, 60, 200), 0)


AUTOMOD_CFG: dict = {"max_mentions": 5, "max_emoji": 12, "dup_count": 3, "dup_window": 20, "allowed_invites": ["abc"]}


class AutomodTests(unittest.TestCase):
    def check(self, text, cfg=None, history=None, now=0.0):
        return automod_rules.check_message(text, {**AUTOMOD_CFG, **(cfg or {})}, history if history is not None else deque(), now)

    def test_invites(self):
        self.assertEqual(self.check("join discord.gg/abc"), [])
        self.assertEqual(self.check("join discord.gg/evil"), ["invite link"])
        self.assertEqual(self.check("https://discord.com/invite/evil"), ["invite link"])

    def test_caps_zalgo_mentions_and_emoji(self):
        self.assertEqual(self.check("THIS IS ALL SHOUTING NOW"), ["caps lock"])
        self.assertEqual(self.check("h" + "̵" * 12 + "i"), ["zalgo text"])
        self.assertEqual(self.check(" ".join(f"<@{i}>" for i in range(6))), ["mass mention"])
        self.assertEqual(self.check("🎉" * 13), ["emoji spam"])

    def test_normal_messages_pass(self):
        self.assertEqual(self.check("Hey, how was the match last night?"), [])

    def test_duplicates_counted_in_window(self):
        history: deque = deque()
        results = [self.check("buy now", history=history, now=t) for t in (0, 1, 2)]
        self.assertEqual(results, [[], [], ["duplicate message"]])
        self.assertEqual(self.check("buy now", history=history, now=100), [])

    def test_blocked_words_and_domains(self):
        self.assertEqual(self.check("you are a Badword", {"words": ["badword"]}), ["blocked word"])
        cfg = {"rules": {"links": True}, "domains": ["bad.example"]}
        self.assertEqual(self.check("see https://sub.bad.example/x", cfg), ["blocked link"])
        self.assertEqual(self.check("see https://good.example/x", cfg), [])

    def test_rules_can_be_switched_off(self):
        self.assertEqual(self.check("THIS IS ALL SHOUTING NOW", {"rules": {"caps": False}}), [])


class AkinatorTests(unittest.TestCase):
    def test_every_character_is_identified_within_twenty_questions(self):
        for target, traits in akinator_engine.CHARACTERS.items():
            with self.subTest(target=target):
                game = akinator_engine.Game()
                solved = None
                while True:
                    if game.should_guess():
                        lead = game.leader()
                        if lead[0] == target:
                            solved = lead[0]
                            break
                        game.reject(lead[0])
                        if not game.posterior():
                            break
                        continue
                    attr = game.next_question()
                    value = traits.get(attr)
                    game.answer(attr, "dont_know" if value is None else ("yes" if value else "no"))
                self.assertEqual(solved, target)
                self.assertLessEqual(len(game.asked), akinator_engine.MAX_QUESTIONS)

    def test_undo_restores_previous_state(self):
        game = akinator_engine.Game()
        before = dict(game.weights)
        attr = game.next_question()
        game.answer(attr, "yes")
        self.assertTrue(game.undo())
        self.assertEqual(game.weights, before)
        self.assertEqual(game.asked, [])
        self.assertFalse(game.undo())


class AniCatchTests(unittest.TestCase):
    def test_pity_guarantees_a_catch(self):
        rng = random.Random(0)
        self.assertTrue(anicatch_engine.attempt_catch(rng, "Sunseraph", anicatch_engine.PITY_MISSES))

    def test_common_catch_rate_is_about_sixty_percent(self):
        hits = sum(anicatch_engine.attempt_catch(random.Random(i), "Emberfox", 0) for i in range(4000))
        self.assertAlmostEqual(hits / 4000, 0.6, delta=0.03)

    def test_battle_power_uses_best_three(self):
        rng = random.Random(0)
        self.assertEqual(anicatch_engine.battle_power({}, rng), 0)
        power = anicatch_engine.battle_power({"Sunseraph": 1, "Emberfox": 1, "Stonepup": 1, "Mossling": 1}, rng)
        self.assertGreaterEqual(power, 60 + 12 + 11)
        self.assertLessEqual(power, int((60 + 12 + 11) * 1.2) + 1)

    def test_spawns_favour_common_creatures(self):
        rng = random.Random(3)
        spawns = [anicatch_engine.roll_spawn(rng) for _ in range(5000)]
        common = sum(anicatch_engine.rarity_of(s) == "common" for s in spawns) / len(spawns)
        self.assertAlmostEqual(common, 0.6, delta=0.03)


class EconomyRuleTests(unittest.TestCase):
    def setUp(self):
        from cogs import economy
        self.economy = economy

    def test_three_matching_pays_six_times(self):
        self.assertEqual(self.economy.slot_return(("🍒", "🍒", "🍒")), 6)

    def test_two_matching_returns_the_bet(self):
        self.assertEqual(self.economy.slot_return(("🍒", "🍒", "🔔")), 1)

    def test_no_match_loses(self):
        self.assertEqual(self.economy.slot_return(("🍒", "🍋", "🔔")), 0)

    def test_slots_have_a_house_edge(self):
        rng = random.Random(42)
        spins = 60_000
        total = sum(self.economy.slot_return(self.economy.spin(rng)) for _ in range(spins))
        expected_return = total / spins
        self.assertGreater(expected_return, 0.85)
        self.assertLess(expected_return, 1.0)

    def test_duration_format(self):
        self.assertEqual(self.economy.format_duration(3725), "1h 2m")
        self.assertEqual(self.economy.format_duration(95), "1m 35s")
        self.assertEqual(self.economy.format_duration(42), "42s")


class GameRuleTests(unittest.TestCase):
    def setUp(self):
        from cogs import games, giveaways
        self.games = games
        self.giveaways = giveaways

    def test_rock_paper_scissors(self):
        self.assertEqual(self.games.rps_outcome("rock", "scissors"), "win")
        self.assertEqual(self.games.rps_outcome("rock", "paper"), "lose")
        self.assertEqual(self.games.rps_outcome("paper", "paper"), "draw")

    def test_streaks_and_numbers(self):
        self.assertEqual(self.games.longest_streak(["heads", "heads", "tails", "heads"], "heads"), 2)
        self.assertEqual(self.games.number_feedback(10, 30), "higher")
        self.assertEqual(self.games.number_feedback(40, 30), "lower")
        self.assertEqual(self.games.number_feedback(30, 30), "correct")

    def test_trivia_bank_is_well_formed(self):
        for question, answer, distractors in self.games.TRIVIA:
            self.assertNotIn(answer, distractors)
            self.assertEqual(len(set(distractors)), 3)
            self.assertLessEqual(len(answer), 80)

    def test_giveaway_winners_are_unique_and_bounded(self):
        rng = random.Random(0)
        winners = self.giveaways.pick_winners([1, 2, 2, 3, 4], 3, rng)
        self.assertEqual(len(winners), 3)
        self.assertEqual(len(set(winners)), 3)
        self.assertEqual(len(self.giveaways.pick_winners([7], 5, rng)), 1)
        self.assertEqual(self.giveaways.pick_winners([], 2, rng), [])


class MusicAndBackupTests(unittest.TestCase):
    def test_queue_is_bounded_and_clean(self):
        q = music_queue.MusicQueue()
        q.add("  Song   One ")
        self.assertEqual(q.items(), ["Song One"])
        for i in range(music_queue.MAX_QUEUE - 1):
            q.add(f"track {i}")
        with self.assertRaises(OverflowError):
            q.add("one too many")
        with self.assertRaises(ValueError):
            music_queue.MusicQueue().add("   ")

    def test_playback_reports_blockers_honestly(self):
        blockers = music_queue.playback_blockers()
        self.assertTrue(any("no playback backend" in b for b in blockers))

    def test_backup_checker(self):
        from cogs.backup import check_backup
        problems, counts = check_backup({"config": {}, "audit": [1, 2]})
        self.assertEqual(problems, [])
        self.assertEqual(counts, {"config": 0, "audit": 2})
        problems, _ = check_backup({"config": []})
        self.assertTrue(problems)
        problems, _ = check_backup(["not", "an", "object"])
        self.assertTrue(problems)


class AIClientTests(unittest.TestCase):
    ENV_KEYS = ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL")

    def test_unconfigured_returns_a_setup_message_not_a_fake_reply(self):
        with patch.dict(os.environ, {k: "" for k in self.ENV_KEYS}):
            self.assertFalse(ai_client.configured())
            with self.assertRaises(ai_client.AIError) as ctx:
                asyncio.run(ai_client.chat("system", "hello"))
        self.assertIn("isn't set up", str(ctx.exception))

    def test_round_trip_against_local_endpoint(self):
        from aiohttp import web

        async def scenario() -> str:
            async def handler(request: web.Request) -> web.Response:
                if request.headers.get("Authorization") != "Bearer test-key-123":
                    return web.Response(status=401)
                return web.json_response({"choices": [{"message": {"content": "hello from the fake endpoint"}}]})

            app = web.Application()
            app.router.add_post("/v1/chat/completions", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                env = {"AI_BASE_URL": f"http://127.0.0.1:{port}/v1", "AI_API_KEY": "test-key-123", "AI_MODEL": "fake-model"}
                with patch.dict(os.environ, env):
                    return await ai_client.chat("system", "hi")
            finally:
                await runner.cleanup()

        self.assertEqual(asyncio.run(scenario()), "hello from the fake endpoint")

    def test_http_errors_do_not_leak_the_key(self):
        from aiohttp import web

        async def scenario() -> str:
            async def handler(request: web.Request) -> web.Response:
                return web.Response(status=500)

            app = web.Application()
            app.router.add_post("/v1/chat/completions", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                env = {"AI_BASE_URL": f"http://127.0.0.1:{port}/v1", "AI_API_KEY": "secret-xyz", "AI_MODEL": "m"}
                with patch.dict(os.environ, env):
                    await ai_client.chat("s", "u")
            except ai_client.AIError as exc:
                return str(exc)
            finally:
                await runner.cleanup()
            return ""

        message = asyncio.run(scenario())
        self.assertIn("HTTP 500", message)
        self.assertNotIn("secret-xyz", message)


class WiringTests(unittest.TestCase):
    """Loads the real bot.py cog list into a bot object without connecting to Discord."""

    @classmethod
    def setUpClass(cls):
        import bot as bot_module
        cls.bot_module = bot_module

    def build(self):
        async def load():
            bot = self.bot_module.Bot()
            failures = []
            for ext in self.bot_module.COGS:
                try:
                    await bot.load_extension(ext)
                except Exception as exc:  # noqa: BLE001 - every failure is collected and asserted below
                    failures.append(f"{ext}: {exc!r}")
            return bot, failures

        return asyncio.run(load())

    def test_every_cog_loads(self):
        _, failures = self.build()
        self.assertEqual(failures, [])

    def test_command_limits_are_respected(self):
        bot, _ = self.build()
        top = bot.tree.get_commands()
        names = [c.name for c in top]
        self.assertEqual(len(names), len(set(names)), "duplicate top-level command names")
        self.assertLessEqual(len(top), 100, "Discord allows at most 100 global slash commands")
        for cmd in top:
            self.assertLessEqual(len(cmd.description), 100, f"description too long: /{cmd.name}")
            if isinstance(cmd, app_commands.Group):
                self.assertLessEqual(len(cmd.commands), 25, f"more than 25 subcommands in /{cmd.name}")
                for sub in cmd.commands:
                    self.assertLessEqual(len(sub.description), 100, f"description too long: /{cmd.name} {sub.name}")

    def test_every_command_maps_to_a_category_or_is_core(self):
        bot, _ = self.build()
        for cmd in bot.tree.get_commands():
            if isinstance(cmd, app_commands.Group):
                for sub in cmd.commands:
                    category = features.category_for(sub.qualified_name)
                    self.assertTrue(category is None or category in catalog.CATEGORIES)

    def test_disabled_module_blocks_its_commands(self):
        bot, _ = self.build()
        gid = 555000111
        features.set_enabled(gid, "economy", False)
        try:
            send = AsyncMock()
            interaction = SimpleNamespace(
                command=SimpleNamespace(qualified_name="eco balance"),
                guild_id=gid,
                response=SimpleNamespace(send_message=send),
            )
            allowed = asyncio.run(EclipseTree.interaction_check(bot.tree, interaction))
            self.assertFalse(allowed)
            send.assert_awaited_once()
            self.assertIn("turned off", send.await_args.args[0])

            features.set_enabled(gid, "economy", True)
            self.assertTrue(asyncio.run(EclipseTree.interaction_check(bot.tree, interaction)))
        finally:
            features.set_enabled(gid, "economy", True)


class TokenTests(unittest.TestCase):
    # Built at runtime so secret scanners don't mistake it for a real token.
    SHAPED = ".".join(["A" * 24, "B" * 6, "C" * 27])

    def test_bad_tokens_are_explained(self):
        from utils import discord_token as dt
        self.assertIn("not set", dt.problem(""))
        self.assertIn("placeholder", dt.problem(dt.PLACEHOLDER))
        self.assertIn("without 'Bot '", dt.problem("Bot " + self.SHAPED))
        self.assertIn("doesn't look like", dt.problem("abc.def"))
        self.assertIsNone(dt.problem(self.SHAPED))

    def test_paste_noise_is_cleaned(self):
        from utils import discord_token as dt
        self.assertEqual(dt.clean(f'  "{self.SHAPED}"\n'), self.SHAPED)

    def test_load_fails_fast_and_never_echoes_the_token(self):
        from utils import discord_token as dt
        with patch.dict(os.environ, {"DISCORD_TOKEN": "not-a-token-xyz"}), self.assertRaises(dt.TokenError) as ctx:
            dt.load()
        self.assertNotIn("not-a-token-xyz", str(ctx.exception))
        self.assertIn("scripts/set_token.py", str(ctx.exception))
        with patch.dict(os.environ, {"DISCORD_TOKEN": f" {self.SHAPED} "}):
            self.assertEqual(dt.load(), self.SHAPED)
        self.assertEqual(dt.describe(self.SHAPED), f"set ({len(self.SHAPED)} characters)")
        self.assertNotIn(self.SHAPED, dt.describe(self.SHAPED))

    def test_save_replaces_only_the_token_line_with_private_permissions(self):
        import tempfile

        sys.path.insert(0, str(ROOT / "scripts"))
        import set_token

        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / ".env.example"
            env = Path(tmp) / ".env"
            example.write_text("# comment\nDISCORD_TOKEN=your-bot-token-here\nDEV_GUILD_ID=123\n", encoding="utf-8")
            set_token.save(self.SHAPED, env_file=env, example_file=example)
            self.assertEqual(env.read_text(encoding="utf-8"), f"# comment\nDISCORD_TOKEN={self.SHAPED}\nDEV_GUILD_ID=123\n")
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertIn("your-bot-token-here", example.read_text(encoding="utf-8"))  # example untouched


if __name__ == "__main__":
    unittest.main(verbosity=2)
