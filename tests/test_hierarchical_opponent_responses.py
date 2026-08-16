from __future__ import annotations

import unittest

from glee_eval.population.opponent_fit import (
    _response_probability,
    _fit_response_coefficients,
    extract_response_observations,
    fit_hierarchical_responses,
    response_probability,
    response_parameter,
)
from glee_eval.population.crossfit import build_manifest, row_fold


def _rows(channel: str, cutoff: float, *, model: str = "m", config: str = "c") -> list[dict]:
    rows = []
    for game in range(18):
        for x in (0.1, 0.3, 0.5, 0.7, 0.9):
            rows.append({"channel": channel, "x": x, "outcome": int(x >= cutoff),
                         "game_id": f"g{game}", "player_model": model, "config_signature": config})
    return rows


class HierarchicalResponseFitTests(unittest.TestCase):
    def test_aggregated_gradient_is_equivalent_to_raw_fixture(self) -> None:
        rows = _rows("bargaining|player_1", 0.5)[:30]
        aggregated = _fit_response_coefficients(rows, 10.0, max_iterations=40, aggregate=True)
        raw = _fit_response_coefficients(rows, 10.0, max_iterations=40, aggregate=False)
        self.assertLess(aggregated["aggregated_rows"], aggregated["raw_rows"])
        self.assertEqual(set(aggregated["coefficients"]), set(raw["coefficients"]))
        for key in aggregated["coefficients"]:
            self.assertAlmostEqual(aggregated["coefficients"][key], raw["coefficients"][key], places=12)

    def test_monotone_threshold_and_training_only_ridge_provenance(self) -> None:
        fit = fit_hierarchical_responses(_rows("bargaining|player_1", 0.5))
        low = _response_probability(fit, {"channel": "bargaining|player_1", "x": 0.2,
                                         "player_model": "m", "config_signature": "c"})
        high = _response_probability(fit, {"channel": "bargaining|player_1", "x": 0.8,
                                          "player_model": "m", "config_signature": "c"})
        threshold, provenance = response_parameter(
            fit, channel="bargaining|player_1", player_model="m", signature="c")
        self.assertLess(low, high)
        self.assertAlmostEqual(high, response_probability(
            fit, channel="bargaining|player_1", player_model="m", signature="c", x=0.8,
        ))
        self.assertGreaterEqual(provenance["monotone_slope"], 0.0)
        self.assertGreaterEqual(threshold, provenance["fit_min"])
        self.assertLessEqual(threshold, provenance["fit_max"])
        self.assertEqual(fit["ridge_grid"], [0.1, 1.0, 10.0, 100.0])
        self.assertIn("three_fold_sha256_game_id", fit["selection"])
        self.assertIn("converged", provenance)

    def test_threshold_clips_only_to_training_x_range(self) -> None:
        rows = _rows("negotiation|seller", 2.0)
        fit = fit_hierarchical_responses(rows)
        threshold, provenance = response_parameter(
            fit, channel="negotiation|seller", player_model="m", signature="c")
        self.assertEqual(threshold, provenance["fit_max"])
        self.assertTrue(provenance["clipped"])

    def test_persuasion_channels_are_separate_partial_pooled_probabilities(self) -> None:
        rows = []
        for game in range(18):
            for channel, hits in (("persuasion|seller_high", 9), ("persuasion|seller_low", 1),
                                  ("persuasion|buyer_yes", 8), ("persuasion|buyer_no", 2)):
                for index in range(10):
                    rows.append({"channel": channel, "x": None, "outcome": int(index < hits),
                                 "game_id": f"{channel}-{game}", "player_model": "m", "config_signature": "c"})
        fit = fit_hierarchical_responses(rows)
        high, _ = response_parameter(fit, channel="persuasion|seller_high", player_model="m", signature="c")
        low, _ = response_parameter(fit, channel="persuasion|seller_low", player_model="m", signature="c")
        buy_yes, _ = response_parameter(fit, channel="persuasion|buyer_yes", player_model="m", signature="c")
        buy_no, _ = response_parameter(fit, channel="persuasion|buyer_no", player_model="m", signature="c")
        self.assertGreater(high, low)
        self.assertGreater(buy_yes, buy_no)
        _, high_provenance = response_parameter(
            fit, channel="persuasion|seller_high", player_model="m", signature="c")
        self.assertEqual(high_provenance["channel_support"]["rows"], 180)
        self.assertEqual(high_provenance["channel_support"]["games"], 18)


class ResponseExtractionTests(unittest.TestCase):
    def test_negotiation_all_legal_decisions_and_buyer_orientation(self) -> None:
        base = {
            "game_family": "negotiation", "role": "buyer", "action_type": "decision",
            "player_1_model": "seller-model", "player_2_model": "buyer-model",
            "configuration": {"buyer_value": 1.0, "seller_value": 0.2, "product_price_order": 100},
            "transcript_so_far": [{"action_type": "offer", "numeric_action": 70.0, "round": 1}],
        }
        events = [
            {**base, "game_id": "accept", "raw_record": {"decision": "AcceptOffer"}},
            {**base, "game_id": "reject", "raw_record": {"decision": "RejectOffer"}},
            {**base, "game_id": "outside", "raw_record": {"decision": "BuyFromJhon"}},
        ]
        rows = extract_response_observations(events)
        self.assertEqual([row["outcome"] for row in rows], [1, 0, 0])
        self.assertTrue(all(abs(row["x"] - 0.3) < 1e-12 for row in rows))
        self.assertTrue(all(row["player_model"] == "buyer-model" for row in rows))

    def test_outer_keep_excludes_rows_before_training_projection(self) -> None:
        events = [
            {"game_family": "persuasion", "role": "buyer", "action_type": "buy_decision",
             "game_id": game, "player_2_model": "m", "configuration": {}, "raw_record": {"decision": "yes"},
             "round": 1, "transcript_so_far": [{"role": "seller", "round": 1, "buy_no_buy": "yes"}]}
            for game in ("keep", "exclude")
        ]
        rows = extract_response_observations(events, outer_keep=lambda event: event["game_id"] == "keep")
        self.assertEqual([row["game_id"] for row in rows], ["keep"])

    def test_manifest_hook_excludes_outer_fold(self) -> None:
        events = [
            {"game_family": "persuasion", "role": "buyer", "action_type": "buy_decision",
             "game_id": f"g{index}", "event_id": f"e{index}", "player_1_model": "seller",
             "player_2_model": f"m{index:02d}", "configuration": {"p": .5, "product_price": 100, "c": 0},
             "raw_record": {"decision": "yes"},
             "round": 1, "transcript_so_far": [{"role": "seller", "round": 1, "buy_no_buy": "yes"}]}
            for index in range(16)
        ]
        manifest = build_manifest(events)
        excluded_fold = 1
        rows = extract_response_observations(
            events, crossfit_manifest=manifest, excluded_fold=excluded_fold, crossfit_axis="actor",
        )
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({row["decision_id"] for row in rows}), 12)
        self.assertTrue(all(row_fold(row, "actor", manifest) != excluded_fold for row in rows))
        expected_config_fold = row_fold(events[0], "config", manifest)
        self.assertTrue(all(row_fold(row, "config", manifest) == expected_config_fold for row in rows))
        self.assertTrue(all("configuration" in row and "player_2_model" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
