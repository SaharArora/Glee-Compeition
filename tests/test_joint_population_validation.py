from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from glee_eval.diagnostics.joint_population import (
    cluster_bootstrap_mean,
    crps,
    energy_score,
    empirical_cdf,
    score_bundle,
    summarize_validation,
    run_validation,
    transform_parameters,
)


class JointPopulationValidationTests(unittest.TestCase):
    def test_transform_uses_fit_marginals_and_mid_ranks(self) -> None:
        transformed = transform_parameters(
            {"x": 2.0, "y": 15.0},
            {"x": [1.0, 2.0, 3.0], "y": [10.0, 20.0]},
            ["x", "y"],
        )
        self.assertAlmostEqual(transformed[0], 0.5)
        self.assertAlmostEqual(transformed[1], 0.5)
        self.assertGreater(empirical_cdf(-100.0, [1.0, 2.0]), 0.0)
        self.assertLess(empirical_cdf(100.0, [1.0, 2.0]), 1.0)

    def test_energy_score_rewards_joint_dependence_not_matching_marginals_alone(self) -> None:
        observed = (0.9, 0.9)
        joint = [(0.1, 0.1), (0.9, 0.9)] * 50
        independent = [(0.1, 0.9), (0.9, 0.1)] * 50
        report = score_bundle(observed, joint, independent)
        self.assertLess(report["energy_delta"], 0.0)

    def test_optimized_scores_equal_direct_pairwise_definitions(self) -> None:
        observed = (0.2, 0.7)
        draws = [(0.1, 0.9), (0.3, 0.4), (0.8, 0.6)]
        first = sum(((x - observed[0]) ** 2 + (y - observed[1]) ** 2) ** 0.5 for x, y in draws) / 3
        second = sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a in draws for b in draws)
        self.assertAlmostEqual(energy_score(observed, draws), first - 0.5 * second / 9)
        scalar = [0.1, 0.3, 0.8]
        direct = sum(abs(x - 0.2) for x in scalar) / 3 - 0.5 * sum(abs(x - y) for x in scalar for y in scalar) / 9
        self.assertAlmostEqual(crps(0.2, scalar), direct)

    def test_joint_scoring_requires_two_parameters(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            score_bundle((0.5,), [(0.5,), (0.6,)], [(0.5,), (0.4,)])

    def test_cluster_bootstrap_is_deterministic_and_clusters_games(self) -> None:
        rows = [
            {"game_id": "a", "delta": 1.0},
            {"game_id": "a", "delta": 1.0},
            {"game_id": "b", "delta": -1.0},
        ]
        first = cluster_bootstrap_mean(rows, "delta", seed=7, replicates=200)
        second = cluster_bootstrap_mean(rows, "delta", seed=7, replicates=200)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["mean"], 1.0 / 3.0)

    def test_summary_refuses_too_few_split_unit_clusters(self) -> None:
        rows = [{"family": "bargaining", "player_model": f"m{i}", "config_id": "c",
                 "role": "player_1", "game_ids": [f"g{i}"], "fallback_levels": {"exact": 1},
                 "v2_neutral_default_values": 0, "v2_requested_parameter_values": 2,
                 "energy_delta": -1.0, "mean_marginal_crps_delta": 0.0,
                 "parameter_names": ["x", "y"], "marginal_crps_deltas": [0.0, 0.0],
                 "observed_rank_values": {"x": 0.2, "y": 0.3},
                 "predictive_moments": {name: {} for name in ("whole_bundle", "conditional_shuffle", "operational_v1")},
                 "support_violations": 0, "nonfinite_draws": 0} for i in range(4)]
        report = summarize_validation(rows, axis="model", replicates=10)
        self.assertFalse(report["families"]["bargaining"]["reportable"])
        self.assertFalse(report["all_families_passed"])

    def test_summary_serializes_and_rejects_a_missing_role(self) -> None:
        rows = [{"family": "bargaining", "player_model": f"m{i}", "config_id": "c",
                 "role": "player_1", "game_ids": [f"g{i}"], "fallback_levels": {"exact": 1},
                 "v2_neutral_default_values": 0, "v2_requested_parameter_values": 2,
                 "energy_delta": -1.0, "operational_v1_energy_delta": -1.0,
                 "mean_marginal_crps_delta": 0.0, "mean_operational_v1_marginal_crps_delta": 0.0,
                 "parameter_names": ["x", "y"], "marginal_crps_deltas": [0.0, 0.0],
                 "operational_v1_marginal_crps_deltas": [0.0, 0.0],
                 "observed_rank_values": {"x": 0.2, "y": 0.3},
                 "predictive_moments": {name: {} for name in ("whole_bundle", "conditional_shuffle", "operational_v1")},
                 "support_violations": 0, "nonfinite_draws": 0} for i in range(5)]
        report = summarize_validation(rows, axis="model", replicates=10,
                                      eligible_game_ids_by_family={"bargaining": {f"g{i}" for i in range(5)}})
        cell = report["families"]["bargaining"]
        self.assertEqual(cell["role_bundle_counts"], {"player_1": 5, "player_2": 0})
        self.assertFalse(cell["reportable"])

    def test_validator_rejects_non_declared_holdout_fraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.json"
            artifact.write_text(json.dumps({"schema_version": 2, "provenance": {
                "split_mode": "model", "split": "fit", "holdout_fraction": 0.2,
            }, "joint_model": {"fit_partition_only": True}}))
            with self.assertRaisesRegex(ValueError, "must be 0.25"):
                run_validation(data_dir=root, artifact_path=artifact, split_mode="model", output_dir=root / "out")


if __name__ == "__main__":
    unittest.main()
