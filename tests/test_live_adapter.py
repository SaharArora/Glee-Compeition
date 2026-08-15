from __future__ import annotations

import copy
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.live import fixtures
from glee_eval.live.schema import (
    MAX_MESSAGE_LEN,
    clamp_message,
    fallback_action,
    negotiation_scale,
    to_game_state,
    to_live_action,
)
from glee_eval.live.strategy import LiveStrategy, build_strategy
from my_agents.jordan_strategic import MyAgent

ALL_GAMES = fixtures.sample_games


def _strategy(agent=None) -> LiveStrategy:
    return LiveStrategy(agent or MyAgent(seed=3), observation_log=None)


class TranslationTests(unittest.TestCase):
    """The live schema differs from ours in seven places; each is pinned here."""

    def test_bargaining_gains_are_named_for_alice_and_bob(self) -> None:
        action = _strategy()(fixtures.bargaining_offer())

        self.assertIn("alice_gain", action)
        self.assertIn("bob_gain", action)
        self.assertNotIn("self_gain", action)

    def test_bargaining_gains_sum_exactly_to_the_pot(self) -> None:
        """The server requires an exact sum, so the counterpart share is derived."""

        for money in (10000, 9999.99, 1, 333.33, 1e6):
            game = fixtures.bargaining_offer(money_to_divide=money)
            action = _strategy()(game)
            self.assertAlmostEqual(action["alice_gain"] + action["bob_gain"], money, places=6, msg=f"money={money}")

    def test_playing_as_bob_puts_our_share_in_bob_gain(self) -> None:
        game = fixtures.bargaining_offer(current_player="player_2", proposer="player_2")
        game["your_player"] = "player_2"

        action = _strategy()(game)

        self.assertGreater(action["bob_gain"], action["alice_gain"])

    def test_negotiation_prices_are_absolute_not_normalised(self) -> None:
        game = fixtures.negotiation_offer()

        action = _strategy()(game)

        # Seller value is 8000; a normalised price near 1.0 must come back near 8000.
        self.assertGreater(action["product_price"], 1000)
        self.assertLess(action["product_price"], 100000)

    def test_negotiation_scale_uses_our_own_valuation(self) -> None:
        self.assertEqual(negotiation_scale(fixtures.negotiation_offer()), 8000)
        self.assertEqual(negotiation_scale(fixtures.negotiation_decision()), 12000)

    def test_persuasion_low_value_u_maps_to_our_c(self) -> None:
        state = to_game_state(fixtures.persuasion_buyer_decision(v=12500, u=2500, product_price=10000))

        self.assertAlmostEqual(state.public_parameters["v"], 1.25)
        self.assertAlmostEqual(state.public_parameters["c"], 0.25)

    def test_persuasion_quality_high_maps_to_high_quality(self) -> None:
        seller = to_game_state(fixtures.persuasion_seller_recommendation(current_quality="high"))
        low = to_game_state(fixtures.persuasion_seller_recommendation(current_quality="low"))

        self.assertEqual(seller.metadata["quality"], "high-quality")
        self.assertEqual(low.metadata["quality"], "low-quality")

    def test_an_absent_max_rounds_becomes_a_long_horizon_not_zero(self) -> None:
        """horizon_known=False means no deadline; horizon 0 would fake an endgame."""

        game = fixtures.bargaining_offer(horizon_known=False)
        del game["game_state"]["max_rounds"]

        state = to_game_state(game)

        self.assertGreater(state.horizon, 10)

    def test_incomplete_information_leaves_the_opponent_value_absent(self) -> None:
        state = to_game_state(fixtures.negotiation_decision(complete_information=False))

        self.assertIn("buyer_value", state.private_parameters)
        self.assertNotIn("seller_value", state.private_parameters)

    def test_complete_information_supplies_both_values(self) -> None:
        game = fixtures.negotiation_decision(complete_information=True, player_1_value=9000)

        state = to_game_state(game)

        self.assertIn("buyer_value", state.private_parameters)
        self.assertIn("seller_value", state.private_parameters)

    def test_documented_histories_are_consumed(self) -> None:
        bargaining = to_game_state(fixtures.bargaining_decision())
        negotiation = to_game_state(fixtures.negotiation_decision())
        persuasion = to_game_state(fixtures.persuasion_buyer_decision())

        self.assertEqual(len([row for row in bargaining.visible_transcript if row["action_type"] == "offer"]), 2)
        self.assertEqual(len([row for row in negotiation.visible_transcript if row["action_type"] == "offer"]), 3)
        self.assertEqual(len([row for row in persuasion.visible_transcript if row["action_type"] == "buy_decision"]), 2)
        self.assertTrue(any(row.get("quality") == "high-quality" for row in persuasion.visible_transcript))

    def test_last_offer_remains_a_compatibility_fallback_without_history(self) -> None:
        game = fixtures.negotiation_decision(history=[])

        state = to_game_state(game)

        offers = [row for row in state.visible_transcript if row["action_type"] == "offer"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["numeric_action"], 11000 / 12000)

    def test_all_fixtures_carry_documented_history_and_persuasion_current_player(self) -> None:
        for game in ALL_GAMES():
            self.assertIsInstance(game["game_state"]["history"], list)
            if game["game_family"] == "persuasion":
                self.assertIn(game["game_state"]["current_player"], {"player_1", "player_2"})


class ActionLegalityTests(unittest.TestCase):
    def test_rejecting_a_negotiation_always_carries_a_counteroffer(self) -> None:
        """RejectOffer without a price is an invalid move and burns an attempt."""

        class AlwaysReject(MyAgent):
            def _negotiation_decision(self, state, control, normalized_price):
                return "RejectOffer"

        action = _strategy(AlwaysReject(seed=1))(fixtures.negotiation_decision())

        self.assertEqual(action["decision"], "RejectOffer")
        self.assertIn("product_price", action)
        self.assertGreater(action["product_price"], 0)

    def test_a_final_round_rejection_needs_no_counteroffer(self) -> None:
        class AlwaysReject(MyAgent):
            def _negotiation_decision(self, state, control, normalized_price):
                return "RejectOffer"

        action = _strategy(AlwaysReject(seed=1))(fixtures.negotiation_decision(round=10, max_rounds=10))

        self.assertEqual(action["decision"], "RejectOffer")
        self.assertNotIn("product_price", action)

    def test_the_offline_outside_option_becomes_walkaway(self) -> None:
        class AlwaysExit(MyAgent):
            def _negotiation_decision(self, state, control, normalized_price):
                return "SellToJhon"

        self.assertEqual(_strategy(AlwaysExit(seed=1))(fixtures.negotiation_decision())["decision"], "WalkAway")

    def test_messages_are_capped_at_the_server_limit(self) -> None:
        class Verbose(MyAgent):
            def _negotiation_message(self, state, control, normalized_price):
                return "x" * (MAX_MESSAGE_LEN + 500)

        action = _strategy(Verbose(seed=1))(fixtures.negotiation_offer())

        self.assertLessEqual(len(action.get("message", "")), MAX_MESSAGE_LEN)

    def test_clamp_message_handles_none_and_short_text(self) -> None:
        self.assertIsNone(clamp_message(None))
        self.assertEqual(clamp_message("hi"), "hi")
        self.assertEqual(len(clamp_message("x" * 5000)), MAX_MESSAGE_LEN)

    def test_no_message_is_sent_when_messages_are_not_allowed(self) -> None:
        action = _strategy()(fixtures.bargaining_offer(messages_allowed=False))

        self.assertNotIn("message", action)

    def test_every_phase_returns_a_dict_with_expected_keys(self) -> None:
        expected = {
            ("bargaining", "offer"): {"alice_gain", "bob_gain"},
            ("bargaining", "decision"): {"decision"},
            ("negotiation", "offer"): {"product_price"},
            ("negotiation", "decision"): {"decision"},
            ("persuasion", "seller_recommendation"): {"decision"},
            ("persuasion", "seller_message"): {"message"},
            ("persuasion", "buyer_decision"): {"decision"},
        }
        strategy = _strategy()
        for game in ALL_GAMES():
            key = (game["game_family"], game["valid_actions"]["type"])
            action = strategy(game)
            self.assertTrue(expected[key] <= set(action), f"{key} produced {action}")

    def test_bargaining_decisions_use_the_live_vocabulary(self) -> None:
        action = _strategy()(fixtures.bargaining_decision())

        self.assertIn(action["decision"], {"accept", "reject", "walkaway"})


class NeverRaiseTests(unittest.TestCase):
    """A raise is not a loud failure here -- the SDK swallows it and submits nothing,
    which the server scores as a turn timeout at the 5th percentile."""

    def test_a_crashing_agent_still_produces_a_legal_move(self) -> None:
        class Broken(MyAgent):
            def decide(self, state):
                raise RuntimeError("boom")

        strategy = _strategy(Broken(seed=1))
        for game in ALL_GAMES():
            action = strategy(game)
            self.assertIsInstance(action, dict)
            self.assertTrue(action, f"empty action for {game['game_family']}")
        self.assertEqual(strategy.summary()["fallbacks"], len(ALL_GAMES()))

    def test_an_agent_raising_a_base_exception_is_also_contained(self) -> None:
        class Nasty(MyAgent):
            def decide(self, state):
                raise KeyboardInterrupt()

        self.assertIsInstance(_strategy(Nasty(seed=1))(fixtures.bargaining_offer()), dict)

    def test_an_agent_returning_nonsense_falls_back(self) -> None:
        class Nonsense(MyAgent):
            def decide(self, state):
                return None

        strategy = _strategy(Nonsense(seed=1))
        action = strategy(fixtures.bargaining_offer())

        self.assertIn("alice_gain", action)
        self.assertGreater(strategy.summary()["fallbacks"], 0)

    def test_an_unknown_family_falls_back_instead_of_raising(self) -> None:
        game = fixtures.bargaining_offer()
        game["game_family"] = "chess"

        action = _strategy()(game)

        self.assertIsInstance(action, dict)
        self.assertTrue(action)

    def test_missing_and_malformed_state_never_raises(self) -> None:
        strategy = _strategy()
        bad_values = [None, {}, "", 0, [], "garbage", float("nan")]
        for game in ALL_GAMES():
            for key in ("game_state", "valid_actions", "your_player", "game_id"):
                for value in bad_values:
                    broken = copy.deepcopy(game)
                    broken[key] = value
                    action = strategy(broken)
                    self.assertIsInstance(action, dict, f"{game['game_family']}/{key}={value!r}")
                    self.assertTrue(action, f"{game['game_family']}/{key}={value!r} produced {action}")

    def test_individually_corrupted_state_fields_never_raise(self) -> None:
        strategy = _strategy()
        bad_values = [None, "x", float("nan"), -1, {}, []]
        for game in ALL_GAMES():
            keys = list((game.get("game_state") or {}).keys())
            for key, value in itertools.product(keys, bad_values):
                broken = copy.deepcopy(game)
                broken["game_state"][key] = value
                action = strategy(broken)
                self.assertIsInstance(action, dict, f"{game['game_family']}/{key}={value!r}")
                self.assertTrue(action)

    def test_an_entirely_empty_payload_never_raises(self) -> None:
        for payload in ({}, {"game_family": "bargaining"}, {"game_family": None}):
            action = _strategy()(payload)
            self.assertIsInstance(action, dict)
            self.assertTrue(action)

    def test_fallback_is_legal_for_every_phase(self) -> None:
        for game in ALL_GAMES():
            action = fallback_action(game)
            self.assertIsInstance(action, dict)
            self.assertTrue(action)
        # A bargaining fallback must still satisfy the exact-sum rule.
        game = fixtures.bargaining_offer(money_to_divide=7777.77)
        action = fallback_action(game)
        self.assertAlmostEqual(action["alice_gain"] + action["bob_gain"], 7777.77, places=6)


class ObservationLogTests(unittest.TestCase):
    def test_every_turn_is_recorded_with_its_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            strategy = LiveStrategy(MyAgent(seed=1), observation_log=path)
            for game in ALL_GAMES():
                strategy(game)

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(len(rows), len(ALL_GAMES()))
            for row in rows:
                self.assertIn("action", row)
                self.assertIn("status", row)
                self.assertIn("elapsed_seconds", row)
                self.assertIn("game_state", row)

    def test_failures_are_recorded_with_the_error(self) -> None:
        class Broken(MyAgent):
            def decide(self, state):
                raise ValueError("nope")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            strategy = LiveStrategy(Broken(seed=1), observation_log=path)
            strategy(fixtures.bargaining_offer())

            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

            self.assertEqual(row["status"], "fallback_after_exception")
            self.assertIn("ValueError", row["error"])

    def test_an_unwritable_log_does_not_cost_a_move(self) -> None:
        strategy = LiveStrategy(MyAgent(seed=1), observation_log="/nonexistent-root/obs.jsonl")

        # The directory cannot be created; the move must still be produced.
        try:
            action = strategy(fixtures.bargaining_offer())
        except Exception as exc:  # pragma: no cover
            self.fail(f"logging failure escaped: {exc}")
        self.assertIsInstance(action, dict)


class BuildStrategyTests(unittest.TestCase):
    def test_build_strategy_loads_the_named_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strategy = build_strategy("my_agents.baseline:MyAgent", observation_log=Path(tmp) / "o.jsonl")
            action = strategy(fixtures.bargaining_offer())

        self.assertIsInstance(action, dict)
        self.assertIn("alice_gain", action)


if __name__ == "__main__":
    unittest.main()


class MarketStatisticsRecoveryTests(unittest.TestCase):
    """Older live payloads may have only running payoff totals.

    Without recovering the buyer's own purchase record from those totals its
    posterior stays pinned at the prior for the whole game, so a truthful seller
    and a liar are indistinguishable to it. Both counts are exactly determined:
    `sold = seller_total / price`, then `h` solves
    `buyer_total = h(v - price) + (sold - h)(u - price)`.
    """

    def _stats(self, **overrides):
        game = fixtures.persuasion_buyer_decision(history=[], **overrides)
        state = to_game_state(game)
        return next(
            (row for row in state.visible_transcript if row.get("action_type") == "market_statistics"),
            None,
        )

    def test_counts_are_recovered_exactly(self) -> None:
        # price 10000, v 12500, u 0. Four sold, three of them high quality:
        # seller_total = 4*10000; buyer_total = 3*2500 + 1*(-10000) = -2500
        stats = self._stats(product_price=10000, v=12500, u=0, seller_total_payoff=40000, buyer_total_payoff=-2500)

        self.assertIsNotNone(stats)
        self.assertEqual(stats["products_sold"], 4)
        self.assertEqual(stats["high_quality_sold"], 3)

    def test_all_high_quality_is_recovered(self) -> None:
        # Five sold, all high: buyer_total = 5*2500
        stats = self._stats(product_price=10000, v=12500, u=0, seller_total_payoff=50000, buyer_total_payoff=12500)

        self.assertEqual(stats["products_sold"], 5)
        self.assertEqual(stats["high_quality_sold"], 5)

    def test_all_low_quality_is_recovered(self) -> None:
        stats = self._stats(product_price=10000, v=12500, u=0, seller_total_payoff=30000, buyer_total_payoff=-30000)

        self.assertEqual(stats["products_sold"], 3)
        self.assertEqual(stats["high_quality_sold"], 0)

    def test_nothing_sold_yet_emits_no_row(self) -> None:
        """With no observations the prior is the correct belief, not a zero row."""

        self.assertIsNone(self._stats(seller_total_payoff=0, buyer_total_payoff=0))

    def test_indeterminate_algebra_is_omitted_rather_than_guessed(self) -> None:
        # v == u leaves h undetermined.
        self.assertIsNone(self._stats(v=10000, u=10000, seller_total_payoff=40000, buyer_total_payoff=0))
        # No price to divide by.
        self.assertIsNone(self._stats(product_price=0, seller_total_payoff=40000, buyer_total_payoff=0))

    def test_missing_totals_are_omitted(self) -> None:
        game = fixtures.persuasion_buyer_decision()
        game["game_state"]["history"] = []
        game["game_state"].pop("seller_total_payoff", None)
        state = to_game_state(game)

        self.assertFalse([r for r in state.visible_transcript if r.get("action_type") == "market_statistics"])

    def test_recovered_counts_are_clamped_to_a_sane_range(self) -> None:
        """Garbage totals must not produce a negative or impossible count."""

        stats = self._stats(product_price=10000, v=12500, u=0, seller_total_payoff=20000, buyer_total_payoff=-10**9)

        self.assertGreaterEqual(stats["high_quality_sold"], 0)
        self.assertLessEqual(stats["high_quality_sold"], stats["products_sold"])

    def test_the_seller_never_receives_market_statistics(self) -> None:
        """It is the buyer's own record; the seller already has full history."""

        state = to_game_state(fixtures.persuasion_seller_recommendation(seller_total_payoff=40000, buyer_total_payoff=0))

        self.assertFalse([r for r in state.visible_transcript if r.get("action_type") == "market_statistics"])

    def test_the_agent_actually_moves_its_posterior_off_the_prior(self) -> None:
        """The point of the whole fix."""

        agent = MyAgent(seed=1)
        frozen = agent._persuasion_beliefs(to_game_state(fixtures.persuasion_buyer_decision(
            history=[], product_price=10000, v=12500, u=0, seller_total_payoff=0, buyer_total_payoff=0)))
        informed = agent._persuasion_beliefs(to_game_state(fixtures.persuasion_buyer_decision(
            history=[], product_price=10000, v=12500, u=0, seller_total_payoff=80000, buyer_total_payoff=20000)))

        self.assertEqual(frozen["market_products_sold"], 0.0)
        self.assertEqual(informed["market_products_sold"], 8.0)
        self.assertGreater(informed["posterior_quality_given_yes"], frozen["posterior_quality_given_yes"])

    def test_a_zero_price_yields_no_statistics(self) -> None:
        """The caller coerces price with `or 1.0`, so this must guard the raw value.

        Regression: it did not, and a 40000 payoff total with price 0 produced
        products_sold = 40000.
        """

        self.assertIsNone(self._stats(product_price=0, seller_total_payoff=40000, buyer_total_payoff=0))

    def test_totals_implying_more_sales_than_rounds_are_rejected(self) -> None:
        stats = self._stats(product_price=10000, v=12500, u=0, total_rounds=20,
                            seller_total_payoff=10000 * 500, buyer_total_payoff=0)

        self.assertIsNone(stats)


class UnboundedHorizonTests(unittest.TestCase):
    """A deadline-free game must not present as a game about to end.

    The adapter stood a horizon of 99 in for "no deadline", which is fine on round 1
    and wrong by round 98: the round counter climbs while the sentinel stays put, so
    the agent's endgame branch -- accept almost anything, or walk away -- fired on a
    number this module invented rather than one the server sent. Live negotiation
    9cf35978 ended that way, a mutual walk-away at round 99 for 0.0/0.0.

    Before this fix a capped-at-99 game and an unbounded one were byte-identical
    downstream, so the log could not tell us which had happened.
    """

    def _negotiation(self, round: int, *, capped: bool) -> dict:
        game = fixtures.negotiation_decision(round=round, max_rounds=99, complete_information=False)
        if not capped:
            del game["game_state"]["max_rounds"]
            game["game_state"]["horizon_known"] = False
        return game

    def _bargaining(self, round: int, *, capped: bool) -> dict:
        game = fixtures.bargaining_offer(round=round, max_rounds=99)
        if not capped:
            del game["game_state"]["max_rounds"]
            game["game_state"]["horizon_known"] = False
        return game

    def test_a_real_cap_is_reported_as_known(self):
        for build in (self._negotiation, self._bargaining):
            state = to_game_state(build(50, capped=True))
            self.assertEqual(state.horizon, 99)
            self.assertIs(state.metadata["horizon_known"], True)

    def test_an_unbounded_game_is_reported_as_unknown(self):
        for build in (self._negotiation, self._bargaining):
            state = to_game_state(build(50, capped=False))
            self.assertIs(state.metadata["horizon_known"], False)

    def test_horizon_known_is_never_none(self):
        """Downstream should not have to tell 'unbounded' from 'nobody said'."""

        game = self._negotiation(5, capped=True)
        del game["game_state"]["horizon_known"]
        self.assertIs(to_game_state(game).metadata["horizon_known"], True)

    def test_the_horizon_rolls_so_remaining_never_runs_down(self):
        agent = MyAgent(seed=1)
        for round_number in (1, 50, 98, 99, 140):
            state = to_game_state(self._negotiation(round_number, capped=False))
            self.assertEqual(
                agent._remaining(state),
                100,
                f"round {round_number} of a deadline-free game should never look near the end",
            )

    def test_a_capped_game_still_reaches_its_endgame(self):
        """The fix must not make every game look infinite -- a real cap still bites."""

        agent = MyAgent(seed=1)
        state = to_game_state(self._negotiation(99, capped=True))
        self.assertEqual(agent._remaining(state), 1)

    def test_the_two_cases_are_now_distinguishable_in_behaviour(self):
        """Probes A and B were identical before, which is why the log was mute."""

        def decision(capped: bool) -> str:
            game = self._negotiation(99, capped=capped)
            game["game_state"].pop("player_1_value", None)
            game["game_state"]["player_2_value"] = 8000
            game["game_state"]["last_offer"] = {
                "price": 9000,
                "message": None,
                "from_player": "player_1",
                "round": 99,
            }
            return LiveStrategy(MyAgent(seed=1), observation_log=None)(game)["decision"]

        self.assertEqual(decision(capped=True), "WalkAway")
        self.assertEqual(decision(capped=False), "RejectOffer")

    def test_an_unbounded_rejection_still_carries_a_counteroffer(self):
        """No cap means no final round, so a bare RejectOffer would be illegal."""

        game = self._negotiation(99, capped=False)
        # An ask above our own value, so rejecting is the correct call and the
        # counteroffer requirement is actually exercised.
        game["game_state"].pop("player_1_value", None)
        game["game_state"]["player_2_value"] = 8000
        game["game_state"]["last_offer"] = {
            "price": 20000,
            "message": None,
            "from_player": "player_1",
            "round": 99,
        }

        payload = LiveStrategy(MyAgent(seed=1), observation_log=None)(game)
        self.assertEqual(payload["decision"], "RejectOffer")
        self.assertIn("product_price", payload)

    def test_the_final_round_of_a_capped_game_sends_no_counteroffer(self):
        """The server takes none there, and sending one is an invalid move."""

        class _Reject:
            structured = {"decision": "RejectOffer"}
            accept_reject = "RejectOffer"
            numeric_action = None
            message = None

        payload = to_live_action(self._negotiation(99, capped=True), _Reject())
        self.assertEqual(payload["decision"], "RejectOffer")
        self.assertNotIn("product_price", payload)
