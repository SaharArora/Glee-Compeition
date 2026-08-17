from __future__ import annotations

import unittest

from glee_eval.diagnostics.leaderboard_proxy_backtest import _episode, invert_displayed_rating
from glee_eval.scoring.shadow import displayed_rating


class LeaderboardProxyBacktestTests(unittest.TestCase):
    def test_displayed_rating_inverse_round_trip(self) -> None:
        for games in (1, 44, 105, 500):
            raw = 1734.25
            displayed = displayed_rating(raw, games)
            self.assertAlmostEqual(invert_displayed_rating(displayed, games), raw, places=10)

    def test_negotiation_live_episode_is_normalized(self) -> None:
        record = {
            "game_family": "negotiation",
            "your_player": "player_1",
            "result": {"player_1_payoff": 20.0},
            "game_state": {
                "player_1_value": 80.0,
                "player_2_value": 120.0,
                "max_rounds": 10,
                "complete_information": True,
                "messages_allowed": False,
                "history": [{"offer": {"price": 100.0}}],
            },
        }
        episode = _episode(record)
        assert episode is not None
        self.assertEqual(episode["role"], "seller")
        self.assertAlmostEqual(episode["payoff"], 0.2)
        self.assertAlmostEqual(episode["config"]["seller_value"], 0.8)


if __name__ == "__main__":
    unittest.main()
