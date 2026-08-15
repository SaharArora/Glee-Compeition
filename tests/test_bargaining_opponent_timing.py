from __future__ import annotations

import unittest

from glee_eval.data.schemas import GameState, OpponentSpec
from glee_eval.opponents.policies import BargainingPolicy


def _state(role: str, round_number: int) -> GameState:
    return GameState(
        scenario_id="timing",
        game_id="timing",
        game_family="bargaining",
        role=role,
        round=round_number,
        horizon=12,
        public_parameters={"money_to_divide": 100, "max_rounds": 12},
        private_parameters={},
        visible_transcript=[],
        valid_action_schema={"kind": "offer"},
    )


class BargainingOpponentTimingTests(unittest.TestCase):
    def _policy(self, archetype: str = "conceding") -> BargainingPolicy:
        return BargainingPolicy(OpponentSpec(
            archetype=archetype,
            game_family="bargaining",
            parameters={"target_share": 0.60, "concession_rate": 0.05, "action_noise": 0.0},
            seed=7,
        ))

    def test_player_one_concedes_once_per_own_offer(self) -> None:
        policy = self._policy()
        shares = [policy.decide(_state("player_1", rnd)).numeric_action / 100 for rnd in (1, 3, 5)]
        self.assertEqual(shares, [0.60, 0.55, 0.50])

    def test_player_two_concedes_once_per_own_offer(self) -> None:
        policy = self._policy()
        shares = [policy.decide(_state("player_2", rnd)).numeric_action / 100 for rnd in (2, 4, 6)]
        self.assertEqual(shares, [0.60, 0.55, 0.50])

    def test_conceding_label_adds_no_unfitted_acceleration(self) -> None:
        conceding = self._policy("conceding")
        neutral = self._policy("historical_imitator")
        for rnd in (1, 3, 5):
            self.assertEqual(
                conceding.decide(_state("player_1", rnd)).numeric_action,
                neutral.decide(_state("player_1", rnd)).numeric_action,
            )


if __name__ == "__main__":
    unittest.main()
