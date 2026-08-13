from __future__ import annotations

import unittest
from dataclasses import replace

from glee_eval.data.ingest import terminal_negotiation
from glee_eval.population.sampler import sample_scenario
from glee_eval.theory.benchmarks import (
    bargaining_spe_shares,
    negotiation_max_surplus,
    persuasion_max_payoff,
    reference_payoff,
)
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import MyAgent


def _negotiation_config(seller_value: float, buyer_value: float, order: float = 1.0) -> dict:
    return {
        "game_type": "negotiation",
        "player_1_args": {"public_name": "Alice"},
        "player_2_args": {"public_name": "Bob"},
        "game_args": {
            "seller_value": seller_value,
            "buyer_value": buyer_value,
            "product_price_order": order,
            "max_rounds": 4,
        },
    }


class BargainingSPETests(unittest.TestCase):
    def test_symmetric_infinite_horizon_limit_matches_rubinstein(self) -> None:
        """With a common delta and a long horizon the proposer share -> 1/(1+delta)."""

        delta = 0.9
        p1, p2 = bargaining_spe_shares({"max_rounds": 200, "delta_1": delta, "delta_2": delta})

        self.assertAlmostEqual(p1, 1.0 / (1.0 + delta), places=6)
        self.assertAlmostEqual(p1 + p2, 1.0, places=9)

    def test_asymmetric_deltas_favour_the_more_patient_player(self) -> None:
        patient_p1, _ = bargaining_spe_shares({"max_rounds": 50, "delta_1": 0.99, "delta_2": 0.70})
        impatient_p1, _ = bargaining_spe_shares({"max_rounds": 50, "delta_1": 0.70, "delta_2": 0.99})

        self.assertGreater(patient_p1, impatient_p1)

    def test_single_round_gives_the_proposer_everything(self) -> None:
        p1, p2 = bargaining_spe_shares({"max_rounds": 1, "delta_1": 0.9, "delta_2": 0.9})

        self.assertAlmostEqual(p1, 1.0)
        self.assertAlmostEqual(p2, 0.0)

    def test_no_discounting_gives_the_last_proposer_everything(self) -> None:
        """With delta=1 and an even horizon, player 2 makes the final offer."""

        p1, p2 = bargaining_spe_shares({"max_rounds": 2, "delta_1": 1.0, "delta_2": 1.0})

        self.assertAlmostEqual(p1, 0.0)
        self.assertAlmostEqual(p2, 1.0)

    def test_shares_stay_in_range_across_the_real_delta_grid(self) -> None:
        for d1 in (0.8, 0.9, 0.95, 1.0):
            for d2 in (0.8, 0.9, 0.95, 1.0):
                for horizon in (1, 2, 3, 12, 30):
                    p1, p2 = bargaining_spe_shares({"max_rounds": horizon, "delta_1": d1, "delta_2": d2})
                    self.assertGreaterEqual(p1, 0.0)
                    self.assertLessEqual(p1, 1.0)
                    self.assertAlmostEqual(p1 + p2, 1.0, places=9)


class NegotiationBenchmarkTests(unittest.TestCase):
    def test_no_trade_zone_has_zero_achievable_surplus(self) -> None:
        self.assertEqual(negotiation_max_surplus({"seller_value": 1.5, "buyer_value": 0.8}), 0.0)
        self.assertEqual(negotiation_max_surplus({"seller_value": 1.0, "buyer_value": 1.0}), 0.0)

    def test_gains_from_trade_is_the_whole_pie(self) -> None:
        self.assertAlmostEqual(negotiation_max_surplus({"seller_value": 0.8, "buyer_value": 1.2}), 0.4)

    def test_missing_values_do_not_invent_a_benchmark(self) -> None:
        self.assertEqual(negotiation_max_surplus({"seller_value": 0.8}), 0.0)
        self.assertEqual(negotiation_max_surplus({}), 0.0)

    def test_reference_payoff_no_longer_returns_the_hardcoded_half(self) -> None:
        """The regression this replaces: optimal play in a no-trade zone was charged 0.5 regret."""

        config = {"seller_value": 1.5, "buyer_value": 0.8, "max_rounds": 10}

        self.assertEqual(reference_payoff("negotiation", "seller", config), 0.0)
        self.assertEqual(reference_payoff("negotiation", "buyer", config), 0.0)


class NegotiationPayoffClampTests(unittest.TestCase):
    def test_accepting_below_your_own_value_now_scores_negative(self) -> None:
        rows = [
            {"player": "Bob", "round": 1, "product_price": 0.6},
            {"player": "Alice", "round": 1, "decision": "AcceptOffer"},
        ]

        terminal = terminal_negotiation(rows, _negotiation_config(seller_value=1.0, buyer_value=1.2))

        self.assertLess(terminal["player_1_payoff"], 0.0)
        self.assertAlmostEqual(terminal["player_1_payoff"], -0.4)

    def test_walking_away_and_destroying_value_are_now_distinguishable(self) -> None:
        config = _negotiation_config(seller_value=1.5, buyer_value=0.8)
        accepted = terminal_negotiation(
            [
                {"player": "Bob", "round": 1, "product_price": 0.8},
                {"player": "Alice", "round": 1, "decision": "AcceptOffer"},
            ],
            config,
        )
        exited = terminal_negotiation(
            [
                {"player": "Bob", "round": 1, "product_price": 0.8},
                {"player": "Alice", "round": 1, "decision": "SellToJhon"},
            ],
            config,
        )

        self.assertLess(accepted["player_1_payoff"], exited["player_1_payoff"])
        self.assertEqual(exited["player_1_payoff"], 0.0)

    def test_total_surplus_is_the_true_pie_not_a_clamped_sum(self) -> None:
        terminal = terminal_negotiation(
            [
                {"player": "Bob", "round": 1, "product_price": 0.9},
                {"player": "Alice", "round": 1, "decision": "AcceptOffer"},
            ],
            _negotiation_config(seller_value=1.5, buyer_value=0.8),
        )

        self.assertAlmostEqual(terminal["realized_surplus"], 0.8 - 1.5)


class PersuasionBenchmarkTests(unittest.TestCase):
    def test_seller_ceiling_is_selling_every_round(self) -> None:
        self.assertEqual(persuasion_max_payoff("seller", {"product_price": 100, "total_rounds": 20}), 1.0)

    def test_buyer_ceiling_is_the_truthful_sender_benchmark(self) -> None:
        value = persuasion_max_payoff("buyer", {"product_price": 100, "total_rounds": 20, "p": 0.5, "v": 1.4})

        self.assertAlmostEqual(value, 0.5 * 0.4)

    def test_buyer_ceiling_ignores_realized_qualities(self) -> None:
        """Perfect foresight would charge the buyer regret for unseen information."""

        config = {"product_price": 100, "total_rounds": 2, "p": 0.5, "v": 1.4}
        lucky = [
            {"action_type": "nature_quality", "product_worth": 140.0},
            {"action_type": "nature_quality", "product_worth": 140.0},
        ]

        self.assertEqual(
            persuasion_max_payoff("buyer", config, lucky),
            persuasion_max_payoff("buyer", config, None),
        )

    def test_buyer_ceiling_is_never_negative(self) -> None:
        value = persuasion_max_payoff("buyer", {"p": 0.1, "v": 1.02, "product_price": 100, "total_rounds": 20})

        self.assertGreaterEqual(value, 0.0)


class IRViolationVisibilityTests(unittest.TestCase):
    def test_an_ir_violating_episode_is_now_flagged(self) -> None:
        """End to end: a no-trade-zone negotiation must not silently score as 0."""

        scenario = sample_scenario("negotiation", seed=5, candidate_role="seller")
        config = dict(scenario.public_parameters)
        config.update({"seller_value": 1.5, "buyer_value": 0.8, "complete_information": True})
        scenario = replace(scenario, public_parameters=config)

        episode = run_episode(scenario, MyAgent(seed=1))

        self.assertEqual(episode.metrics["reference_payoff"], max(0.0, episode.candidate_payoff))
        if episode.candidate_payoff < 0:
            self.assertEqual(episode.metrics["ir_violation"], 1.0)


if __name__ == "__main__":
    unittest.main()
