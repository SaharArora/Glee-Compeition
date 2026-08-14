"""Exercise our strategy through the SDK's own call path, with no network.

`GleeClient._handle_game` is the code that will actually invoke us in the
competition, and its behaviour on failure is the whole reason the adapter is built
the way it is: it catches a strategy exception, logs it, and returns *without
submitting a move*. Testing against our own harness would not prove we survive
that path, so these tests drive the real SDK object with `move` stubbed out.

Skipped when glee-sdk is not importable, so the offline suite still runs on an
interpreter without it.
"""

from __future__ import annotations

import unittest

from glee_eval.live import fixtures
from glee_eval.live.strategy import LiveStrategy
from my_agents.jordan_strategic import MyAgent

try:
    from glee_sdk import GleeClient

    HAVE_SDK = True
except ImportError:  # pragma: no cover - depends on the local environment
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, "glee-sdk is not installed in this interpreter")
class SdkCallPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.submitted: list[tuple[str, dict]] = []

        class OfflineClient(GleeClient):
            def __init__(inner):
                super().__init__(api_key="test-key")

            def move(inner, game_id: str, action: dict) -> dict:
                self.submitted.append((game_id, action))
                return {"valid": True, "game_over": False}

        self.client = OfflineClient()

    def test_every_phase_submits_a_move_through_the_sdk(self) -> None:
        strategy = LiveStrategy(MyAgent(seed=5), observation_log=None)

        for game in fixtures.sample_games():
            self.client._handle_game(strategy, game)

        self.assertEqual(len(self.submitted), len(fixtures.sample_games()))
        for _, action in self.submitted:
            self.assertIsInstance(action, dict)
            self.assertTrue(action)

    def test_a_crashing_agent_still_submits_rather_than_timing_out(self) -> None:
        """The failure mode this whole layer exists to prevent.

        A raise reaches `_handle_game`, which swallows it and submits nothing --
        the server then times the turn out and scores it at the 5th percentile.
        """

        class Broken(MyAgent):
            def decide(self, state):
                raise RuntimeError("boom")

        strategy = LiveStrategy(Broken(seed=5), observation_log=None)

        for game in fixtures.sample_games():
            self.client._handle_game(strategy, game)

        self.assertEqual(len(self.submitted), len(fixtures.sample_games()))

    def test_a_raising_strategy_would_submit_nothing(self) -> None:
        """Demonstrates the hazard, so the guarantee above is not taken on faith."""

        def raising_strategy(game: dict) -> dict:
            raise RuntimeError("boom")

        finished = self.client._handle_game(raising_strategy, fixtures.bargaining_offer())

        self.assertFalse(finished)
        self.assertEqual(self.submitted, [], "the SDK submits nothing when the strategy raises")

    def test_an_invalid_move_response_is_tolerated(self) -> None:
        class RejectingClient(GleeClient):
            def __init__(inner):
                super().__init__(api_key="test-key")

            def move(inner, game_id: str, action: dict) -> dict:
                return {"valid": False, "error": "bad shape", "attempts_left": 3, "game_over": False}

        strategy = LiveStrategy(MyAgent(seed=5), observation_log=None)

        finished = RejectingClient()._handle_game(strategy, fixtures.bargaining_offer())

        self.assertFalse(finished)

    def test_game_over_is_reported_back(self) -> None:
        class FinishingClient(GleeClient):
            def __init__(inner):
                super().__init__(api_key="test-key")

            def move(inner, game_id: str, action: dict) -> dict:
                return {"valid": True, "game_over": True, "result": {"payoff": 1.0}}

        strategy = LiveStrategy(MyAgent(seed=5), observation_log=None)

        self.assertTrue(FinishingClient()._handle_game(strategy, fixtures.bargaining_offer()))

    def test_message_lengths_respect_the_sdk_constant(self) -> None:
        from glee_sdk.client import MAX_MESSAGE_LEN as SDK_MAX

        from glee_eval.live.schema import MAX_MESSAGE_LEN as OURS

        self.assertEqual(OURS, SDK_MAX, "our cap must track the SDK's")

    def test_strategy_is_accepted_where_run_expects_a_callable(self) -> None:
        strategy = LiveStrategy(MyAgent(seed=5), observation_log=None)

        self.assertTrue(callable(strategy))
        action = strategy(fixtures.negotiation_offer())
        self.assertIsInstance(action, dict)


if __name__ == "__main__":
    unittest.main()
