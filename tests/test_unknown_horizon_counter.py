from __future__ import annotations

import unittest

from glee_eval.data.schemas import Scenario
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import MyAgent, UnknownHorizonCounterFallbackCandidate


def _scenario() -> Scenario:
    return Scenario(
        scenario_id="hidden-counter",
        game_family="negotiation",
        config_id="cfg",
        public_parameters={
            "seller_value": 1.5,
            "buyer_value": 1.6,
            "product_price_order": 10_000,
            "max_rounds": 10,
            "complete_information": True,
            "messages_allowed": False,
        },
        candidate_role="seller",
        opponent_role="buyer",
        opponent_spec={
            "archetype": "aggressive_extractor",
            "game_family": "negotiation",
            "parameters": {"aspiration_price": 1.0, "accept_margin": 0.1, "concession_rate": 0.0},
            "seed": 3,
        },
        seed=4,
        metadata={"live_contract_hidden_horizon": True},
    )


class UnknownHorizonCounterTests(unittest.TestCase):
    def test_flag_defaults_off(self) -> None:
        self.assertFalse(MyAgent().use_unknown_horizon_counter_fallback)
        self.assertTrue(UnknownHorizonCounterFallbackCandidate().use_unknown_horizon_counter_fallback)

    def test_candidate_counter_is_positive_and_never_worsens_last_offer(self) -> None:
        episode = run_episode(_scenario(), UnknownHorizonCounterFallbackCandidate())
        decisions = [r for r in episode.decision_records if r.role == "seller" and r.action["action_type"] == "decision"]
        self.assertTrue(decisions)
        for record in decisions:
            if record.action.get("accept_reject") != "RejectOffer":
                continue
            counter = record.action["structured"]["counter_price"]
            self.assertGreater(counter, 15_000)
            prior_own = [
                row["numeric_action"] for row in record.visible_state["visible_transcript"]
                if row.get("role") == "seller" and row.get("action_type") == "offer"
            ]
            if prior_own:
                self.assertLessEqual(counter, prior_own[-1])

    def test_hidden_engine_cap_remains_terminal(self) -> None:
        episode = run_episode(_scenario(), MyAgent())
        self.assertLessEqual(len(episode.decision_records), 20)
        self.assertIn(episode.terminal_outcome["result"], {"AcceptOffer", "WalkAway", "SellToJhon", "BuyFromJhon", "no_deal"})


if __name__ == "__main__":
    unittest.main()
