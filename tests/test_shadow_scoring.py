from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from glee_eval.scoring.shadow import build_reference_tables, score_episodes, shadow_score
from glee_eval.storage.trajectories import write_jsonl


class ShadowScoringTests(unittest.TestCase):
    def test_negotiation_trade_zone_diagnostic_does_not_change_primary_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_trade = {"seller_value": 0.8, "buyer_value": 0.6}
            gains = {"seller_value": 0.2, "buyer_value": 0.9}
            games = []
            for index, payoff in enumerate([0.0, 0.0, 0.0, 0.0]):
                games.append({"game_id": f"n{index}", "game_family": "negotiation", "configuration": {"game_args": no_trade}, "player_1_payoff": payoff})
            for index, payoff in enumerate([0.1, 0.3, 0.5, 0.7]):
                games.append({"game_id": f"g{index}", "game_family": "negotiation", "configuration": {"game_args": gains}, "player_1_payoff": payoff})
            games_path = root / "games.jsonl"
            write_jsonl(games_path, games)
            episodes_path = root / "episodes.jsonl"
            no_trade_episode = {**no_trade, "max_rounds": 99}
            gains_episode = {**gains, "max_rounds": 99}
            write_jsonl(episodes_path, [
                {"episode_id": "no-trade", "scenario": {"game_family": "negotiation", "candidate_role": "seller", "public_parameters": no_trade_episode}, "candidate_payoff": 0.0},
                {"episode_id": "gains", "scenario": {"game_family": "negotiation", "candidate_role": "seller", "public_parameters": gains_episode}, "candidate_payoff": 0.3},
            ])
            reference = build_reference_tables(games_path)

            rows, summary = score_episodes(episodes_path, reference, min_reference=20)

            self.assertEqual([row["bucket_level"] for row in rows], ["family_role", "family_role"])
            self.assertEqual([row["percentile"] for row in rows], [0.25, 0.6875])
            self.assertEqual([row["trade_zone_stratified_percentile"] for row in rows], [0.5, 0.375])
            warning = summary["families"]["negotiation"]["percentile_stratification_warning"]
            self.assertIsNotNone(warning)
            self.assertEqual(warning["episodes_by_zone"], {"no_trade_zone": 1, "gains_from_trade": 1})
            self.assertEqual(summary["trade_zone_diagnostic"], "reported_separately_and_never_used_for_rating")

    def test_missing_negotiation_values_suppress_trade_zone_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"max_rounds": 1}
            games_path = root / "games.jsonl"
            write_jsonl(games_path, [{"game_id": "n", "game_family": "negotiation", "configuration": {"game_args": config}, "player_1_payoff": 0.0}])
            episodes_path = root / "episodes.jsonl"
            write_jsonl(episodes_path, [{"episode_id": "n", "scenario": {"game_family": "negotiation", "candidate_role": "seller", "public_parameters": config}, "candidate_payoff": 0.0}])

            rows, summary = score_episodes(episodes_path, build_reference_tables(games_path), min_reference=1)

            self.assertIsNone(rows[0]["trade_zone"])
            self.assertIsNone(rows[0]["trade_zone_stratified_percentile"])
            self.assertIsNone(summary["families"]["negotiation"]["percentile_stratification_warning"])

    def test_shadow_score_uses_exact_role_config_percentiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config = {"money_to_divide": 100, "max_rounds": 6, "complete_information": True, "messages_allowed": False}
            games = [
                {
                    "game_id": f"g{i}",
                    "game_family": "bargaining",
                    "configuration": {"game_args": config},
                    "player_1_payoff": payoff,
                    "player_2_payoff": 1.0 - payoff,
                }
                for i, payoff in enumerate([0.1, 0.3, 0.5, 0.7, 0.9], start=1)
            ]
            write_jsonl(data_dir / "processed" / "games.jsonl", games)
            episodes = [
                {
                    "episode_id": "candidate-1",
                    "scenario": {
                        "game_family": "bargaining",
                        "candidate_role": "player_1",
                        "public_parameters": config,
                    },
                    "candidate_payoff": 0.7,
                }
            ]
            episodes_path = root / "episodes.jsonl"
            write_jsonl(episodes_path, episodes)

            reference = build_reference_tables(data_dir / "processed" / "games.jsonl")
            rows, summary = score_episodes(episodes_path, reference, min_reference=1)

            self.assertEqual(rows[0]["bucket_level"], "exact")
            self.assertAlmostEqual(rows[0]["percentile"], 0.7)
            self.assertAlmostEqual(rows[0]["game_rating"], 3600.0)
            self.assertGreater(summary["families"]["bargaining"]["raw_rating"], 1000.0)

    def test_shadow_score_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config = {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6}
            games = [
                {
                    "game_id": f"n{i}",
                    "game_family": "negotiation",
                    "configuration": {"game_args": config},
                    "player_1_payoff": payoff,
                    "player_2_payoff": 0.4 - payoff,
                }
                for i, payoff in enumerate([0.02, 0.08, 0.16, 0.24], start=1)
            ]
            write_jsonl(data_dir / "processed" / "games.jsonl", games)
            episodes_path = root / "run" / "datasets" / "episode_summary.jsonl"
            write_jsonl(
                episodes_path,
                [
                    {
                        "episode_id": "candidate-n",
                        "scenario": {
                            "game_family": "negotiation",
                            "candidate_role": "seller",
                            "public_parameters": config,
                        },
                        "candidate_payoff": 0.16,
                    }
                ],
            )

            result = shadow_score(episodes_path, data_dir=data_dir, output_dir=root / "out", min_reference=1)

            self.assertTrue((root / "out" / "shadow_score.md").exists())
            self.assertTrue((root / "out" / "scored_episodes.jsonl").exists())
            self.assertIn("overall_displayed_rating", result["summary"])


if __name__ == "__main__":
    unittest.main()
