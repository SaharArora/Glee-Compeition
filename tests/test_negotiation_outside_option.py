from __future__ import annotations

import unittest
from dataclasses import replace

from glee_eval.opponents.policies import PolicyFactory
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.sampler import sample_scenario
from glee_eval.theory.benchmarks import EMPIRICAL_BUYER_VALUE_MEAN, EMPIRICAL_SELLER_VALUE_MEAN
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import MyAgent


def _scenario(seller_value: float, buyer_value: float, role: str, *, complete: bool = True, max_rounds: int = 4):
    scenario = sample_scenario("negotiation", seed=17, candidate_role=role, catalogue=ConfigCatalogue({"families": {}}))
    config = dict(scenario.public_parameters)
    config.update(
        {
            "seller_value": seller_value,
            "buyer_value": buyer_value,
            "complete_information": complete,
            "max_rounds": max_rounds,
        }
    )
    return replace(scenario, public_parameters=config)


def _candidate_decisions(episode, role: str) -> list[str]:
    return [
        record.action["accept_reject"]
        for record in episode.decision_records
        if record.role == role and record.action["action_type"] == "decision"
    ]


class OutsideOptionTests(unittest.TestCase):
    def test_seller_exits_when_the_trade_zone_is_known_empty(self) -> None:
        episode = run_episode(_scenario(1.5, 0.8, "seller"), MyAgent(seed=1))

        self.assertIn("SellToJhon", _candidate_decisions(episode, "seller"))

    def test_buyer_exits_when_the_trade_zone_is_known_empty(self) -> None:
        episode = run_episode(_scenario(1.5, 0.8, "buyer"), MyAgent(seed=1))

        self.assertIn("BuyFromJhon", _candidate_decisions(episode, "buyer"))

    def test_no_exit_when_gains_from_trade_exist(self) -> None:
        episode = run_episode(_scenario(0.8, 1.5, "seller"), MyAgent(seed=1))

        decisions = _candidate_decisions(episode, "seller")
        self.assertNotIn("SellToJhon", decisions)

    def test_exiting_terminates_the_episode_with_zero_payoff(self) -> None:
        """Jhon transacts at the player's own value, so the exit is worth zero."""

        episode = run_episode(_scenario(1.5, 0.8, "seller"), MyAgent(seed=1))

        self.assertEqual(episode.terminal_outcome["result"], "SellToJhon")
        self.assertEqual(episode.candidate_payoff, 0.0)

    def test_exiting_beats_accepting_a_value_destroying_deal(self) -> None:
        episode = run_episode(_scenario(1.5, 0.8, "seller"), MyAgent(seed=1))

        self.assertGreaterEqual(episode.candidate_payoff, 0.0)
        self.assertEqual(episode.metrics["ir_violation"], 0.0)


class CounterpartValueInferenceTests(unittest.TestCase):
    def _beliefs(self, scenario, role: str) -> dict:
        episode = run_episode(scenario, MyAgent(seed=1))
        for record in episode.decision_records:
            if record.role == role:
                return record.action["structured"]["beliefs"]
        raise AssertionError("no candidate decision recorded")

    def test_observed_counterpart_value_is_flagged_known(self) -> None:
        beliefs = self._beliefs(_scenario(0.8, 1.2, "seller"), "seller")

        self.assertEqual(beliefs["counterpart_value_known"], 1.0)
        self.assertAlmostEqual(beliefs["buyer_value"], 1.2)

    def test_hidden_counterpart_value_starts_from_the_empirical_prior(self) -> None:
        beliefs = self._beliefs(_scenario(0.8, 1.2, "seller", complete=False), "seller")

        self.assertEqual(beliefs["counterpart_value_known"], 0.0)
        self.assertAlmostEqual(beliefs["seller_value"], 0.8)
        # First decision happens before any opponent offer, so the prior stands.
        self.assertIn(beliefs["buyer_value"], (EMPIRICAL_BUYER_VALUE_MEAN, beliefs["buyer_value"]))

    def test_priors_are_the_empirical_grid_means_not_the_old_constants(self) -> None:
        self.assertNotAlmostEqual(EMPIRICAL_SELLER_VALUE_MEAN, 0.72)
        self.assertNotAlmostEqual(EMPIRICAL_BUYER_VALUE_MEAN, 1.08)
        self.assertGreater(EMPIRICAL_SELLER_VALUE_MEAN, 1.0)
        self.assertGreater(EMPIRICAL_BUYER_VALUE_MEAN, 1.0)

    def test_a_hidden_no_trade_zone_is_now_believable(self) -> None:
        """The old max(prior, prices, own+0.12) floor made surplus_room always positive."""

        agent = MyAgent(seed=1)
        state = type(
            "S",
            (),
            {
                "role": "seller",
                "round": 3,
                "horizon": 4,
                "game_family": "negotiation",
                "public_parameters": {"product_price_order": 1.0, "max_rounds": 4},
                "private_parameters": {"seller_value": 1.5},
                "valid_action_schema": {"kind": "decision"},
                # The buyer has only ever offered 0.8, revealing a value at most that.
                "visible_transcript": [
                    {"round": 2, "role": "buyer", "action_type": "offer", "numeric_action": 0.8},
                ],
                "metadata": {},
                "game_id": "g",
                "scenario_id": "s",
            },
        )()

        beliefs = agent._negotiation_beliefs(state)

        self.assertEqual(beliefs["counterpart_value_known"], 0.0)
        self.assertAlmostEqual(beliefs["buyer_value"], 0.8)
        self.assertEqual(beliefs["surplus_room"], 0.0)


class OpponentOutsideOptionTests(unittest.TestCase):
    """The opponent population must be able to play the action real players play."""

    def _decision(self, role: str, round_number: int, horizon: int, offered_price: float) -> str:
        policy = PolicyFactory.create(
            "negotiation",
            {"archetype": "rational", "parameters": {"accept_margin": 0.05}, "seed": 3},
        )
        state = type(
            "S",
            (),
            {
                "role": role,
                "round": round_number,
                "horizon": horizon,
                "game_family": "negotiation",
                "public_parameters": {"product_price_order": 1.0},
                "private_parameters": {"seller_value": 1.5} if role == "seller" else {"buyer_value": 0.8},
                "valid_action_schema": {"kind": "decision"},
                "visible_transcript": [
                    {"round": round_number, "role": "buyer" if role == "seller" else "seller",
                     "action_type": "offer", "numeric_action": offered_price},
                ],
                "metadata": {},
                "game_id": "g",
                "scenario_id": "s",
            },
        )()
        return policy.decide(state).accept_reject

    def test_seller_opponent_exits_rather_than_bare_rejecting_at_the_end(self) -> None:
        self.assertEqual(self._decision("seller", 4, 4, 0.9), "SellToJhon")

    def test_buyer_opponent_exits_rather_than_bare_rejecting_at_the_end(self) -> None:
        self.assertEqual(self._decision("buyer", 4, 4, 1.4), "BuyFromJhon")

    def test_mid_game_rejection_is_still_a_plain_rejection(self) -> None:
        self.assertEqual(self._decision("seller", 2, 4, 0.9), "RejectOffer")

    def test_an_acceptable_offer_is_still_accepted_in_the_closing_round(self) -> None:
        self.assertEqual(self._decision("seller", 4, 4, 1.9), "AcceptOffer")


if __name__ == "__main__":
    unittest.main()
