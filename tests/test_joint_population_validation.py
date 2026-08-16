from __future__ import annotations

import unittest
import json
import tempfile
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from glee_eval.diagnostics.joint_population import (
    binary_log_loss,
    brier_score,
    cluster_bootstrap_mean,
    crps,
    energy_score,
    empirical_cdf,
    score_bundle,
    score_oof_decision,
    score_crossfit_bundles,
    score_crossfit_decisions,
    decision_comparator_probabilities,
    summarize_oof_decisions,
    summarize_validation,
    run_validation,
    response_fit_provenance_errors,
    transform_parameters,
)


class JointPopulationValidationTests(unittest.TestCase):
    def test_oof_decision_scores_are_paired_against_both_declared_comparators(self) -> None:
        scored = score_oof_decision(
            outcome=1, model_b_probability=0.8, neutral_probability=0.5, v1_probability=0.6,
        )
        self.assertLess(scored["neutral_log_loss_delta"], 0.0)
        self.assertLess(scored["v1_log_loss_delta"], 0.0)
        self.assertLess(scored["neutral_brier_delta"], 0.0)
        self.assertLess(scored["v1_brier_delta"], 0.0)

    def test_oof_decision_scores_reject_nonfinite_or_out_of_domain_probabilities(self) -> None:
        for probability in (-0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "finite and in"):
                binary_log_loss(1, probability)
            with self.assertRaisesRegex(ValueError, "finite and in"):
                brier_score(0, probability)

    def test_decision_comparators_mirror_neutral_and_256_draw_v1_semantics(self) -> None:
        class Population:
            def parameters(self, family, archetype, rng, role=None):
                if family == "bargaining":
                    return {"accept_threshold": 0.4}
                return {"honesty": 0.8, "yes_on_low_rate": 0.1,
                        "trust_prior": 0.7, "buy_after_no_rate": 0.03}

        neutral, v1 = decision_comparator_probabilities(
            {}, {"family": "bargaining", "role": "player_1", "channel": "bargaining|player_1",
                 "x": 0.5, "decision_id": "d"}, population=Population(),
        )
        self.assertEqual((neutral, v1), (1.0, 1.0))
        neutral, v1 = decision_comparator_probabilities(
            {}, {"family": "persuasion", "role": "seller", "channel": "persuasion|seller_low",
                 "x": None, "decision_id": "d"}, population=Population(),
        )
        self.assertAlmostEqual(neutral, 0.4)
        self.assertAlmostEqual(v1, 0.1)

    def test_crossfit_decision_orchestration_requires_unique_stable_ids(self) -> None:
        class Router:
            manifest = {"manifest_sha256": "manifest"}

            def route(self, row):
                return SimpleNamespace(fold=0, sha256="sha", path=Path("fold.json"), payload={})

        row = {"decision_id": "d", "family": "bargaining", "channel": "bargaining|player_1"}
        with self.assertRaisesRegex(ValueError, "duplicate OOF decision"):
            score_crossfit_decisions([row, row], Router())

    def test_crossfit_decisions_route_then_pool_with_complete_provenance(self) -> None:
        def inner_records(loss):
            return [{
                "fold": fold, "training_rows": 20, "validation_rows": 10,
                "training_games": 10, "validation_games": 5, "converged": True,
                "stop_reason": "projected_kkt", "projected_kkt_norm": 5e-8,
                "projected_kkt_tolerance": 1e-7, "projected_kkt_pass": True,
                "iterations": 3, "finite_validation_probability": True,
                "finite_validation_loss": True, "fold_logloss": loss,
            } for fold in range(3)]

        fit = {
            "status": "ok", "reason": None, "ridge_grid": [0.1, 1, 10, 100],
            "cv_log_loss": {"0.1": 0.4, "1.0": 0.3, "10.0": 0.2, "100.0": 0.1},
            "inner_cv_convergence": {
                "0.1": inner_records(0.4), "1.0": inner_records(0.3),
                "10.0": inner_records(0.2), "100.0": inner_records(0.1),
            },
            "eligible_ridges": [0.1, 1.0, 10.0, 100.0], "selected_ridge": 100, "ridge": 100,
            "selection": "three_fold_sha256_game_id; minimum pooled validation-decision logloss; exact ties choose larger ridge",
            "ridge_tie_rule": "minimum pooled validation-decision logloss; exact ties choose larger ridge",
            "converged": True, "iterations": 3, "max_iterations": 300, "tolerance": 1e-7,
            "optimizer": "sparse_coordinate_newton_with_deterministic_backtracking",
            "final_objective": 0.5, "objective_history": [1.0, 0.5], "final_max_change": 1e-8,
            "final_max_gradient": 5e-8, "projected_kkt_tolerance": 1e-7,
            "projected_kkt_pass": True, "stop_reason": "projected_kkt", "last_damping": 1.0,
            "total_backtracks": 0, "coefficients": {"intercept|persuasion|buyer_yes": 0.1},
            "x_scale": {"persuasion|buyer_yes": {"mean": 0.0, "sd": 1.0, "min": None, "max": None}},
            "raw_rows": 20, "aggregated_rows": 10, "numerical_sufficient_statistic_rows": 10,
            "aggregation_enabled": True, "training_rows": 20,
            "channel_support": {"persuasion|buyer_yes": {
                "rows": 20, "games": 10, "models": 4, "config_signatures": 5,
            }},
        }

        class Router:
            manifest = {"manifest_sha256": "manifest"}

            def route(self, row):
                fold = int(row["assigned_fold"])
                return SimpleNamespace(
                    fold=fold, sha256=f"sha-{fold}", path=Path(f"fold-{fold}.json"),
                    payload={"joint_model": {"response_estimators": {"persuasion": fit}}},
                )

        rows = [{
            "decision_id": f"d{fold}", "assigned_fold": fold, "family": "persuasion",
            "role": "buyer", "channel": "persuasion|buyer_yes", "outcome": 1, "x": None,
            "game_id": f"g{fold}", "player_model": f"m{fold}", "config_signature": f"c{fold}",
        } for fold in (3, 0, 2, 1)]
        with patch("glee_eval.diagnostics.joint_population.OpponentPopulation", return_value=object()), \
             patch("glee_eval.diagnostics.joint_population.response_probability", return_value=0.8), \
             patch("glee_eval.diagnostics.joint_population.decision_comparator_probabilities", return_value=(0.55, 0.6)):
            pooled, eligible = score_crossfit_decisions(rows, Router())
        self.assertEqual([row["outer_fold"] for row in pooled], [0, 1, 2, 3])
        self.assertTrue(all(row["provenance_complete"] for row in pooled))
        self.assertEqual(eligible[("persuasion", "persuasion|buyer_yes")]["decisions"], 4)
        fit["final_max_gradient"] = 2e-7
        with patch("glee_eval.diagnostics.joint_population.OpponentPopulation", return_value=object()), \
             patch("glee_eval.diagnostics.joint_population.response_probability", return_value=0.8), \
             patch("glee_eval.diagnostics.joint_population.decision_comparator_probabilities", return_value=(0.55, 0.6)):
            rejected, rejected_eligible = score_crossfit_decisions(rows, Router())
        self.assertEqual(rejected, [])
        self.assertIn(
            "projected_kkt_residual_exceeds_tolerance",
            rejected_eligible[("persuasion", "persuasion|buyer_yes")]["provenance_errors"],
        )

    def test_response_fit_provenance_enforces_kkt_inner_cv_and_selection(self) -> None:
        def record(fold, loss):
            return {"fold": fold, "training_rows": 20, "validation_rows": 10,
                    "training_games": 10, "validation_games": 5, "converged": True,
                    "stop_reason": "projected_kkt", "projected_kkt_norm": 5e-8,
                    "projected_kkt_tolerance": 1e-7, "projected_kkt_pass": True,
                    "iterations": 4, "finite_validation_probability": True,
                    "finite_validation_loss": True, "fold_logloss": loss}

        losses = {"0.1": 0.4, "1.0": 0.3, "10.0": 0.2, "100.0": 0.1}
        fit = {"status": "ok", "reason": None,
               "optimizer": "sparse_coordinate_newton_with_deterministic_backtracking",
               "converged": True, "projected_kkt_pass": True, "stop_reason": "projected_kkt",
               "max_iterations": 300, "iterations": 5, "tolerance": 1e-7,
               "projected_kkt_tolerance": 1e-7, "final_max_gradient": 5e-8,
               "final_max_change": 1e-8, "final_objective": 0.5,
               "objective_history": [1.0, 0.75, 0.5], "last_damping": 0.5,
               "total_backtracks": 1, "coefficients": {"intercept|x": 0.0, "slope|x": 1e-8},
               "x_scale": {"x": {"mean": 0.0, "sd": 1.0, "min": -1.0, "max": 1.0}},
               "raw_rows": 20, "aggregated_rows": 10, "numerical_sufficient_statistic_rows": 10,
               "aggregation_enabled": True, "training_rows": 20,
               "ridge_grid": [0.1, 1, 10, 100], "cv_log_loss": losses,
               "inner_cv_convergence": {key: [record(fold, loss) for fold in range(3)]
                                         for key, loss in losses.items()},
               "eligible_ridges": [0.1, 1.0, 10.0, 100.0], "selected_ridge": 100,
               "ridge": 100,
               "selection": "three_fold_sha256_game_id; minimum pooled validation-decision logloss; exact ties choose larger ridge",
               "ridge_tie_rule": "minimum pooled validation-decision logloss; exact ties choose larger ridge"}
        self.assertEqual(response_fit_provenance_errors(fit), [])

        mutations = {
            "kkt": lambda item: item.update(final_max_gradient=2e-7),
            "stagnation": lambda item: item.update(stop_reason="line_search_stagnation"),
            "slope": lambda item: item["coefficients"].update({"slope|x": 0.0}),
            "objective": lambda item: item.update(objective_history=[1.0, 1.1, 0.5]),
            "selection": lambda item: item.update(selected_ridge=10, ridge=10),
            "nonfinite": lambda item: item["coefficients"].update({"intercept|x": float("nan")}),
            "inner": lambda item: item["inner_cv_convergence"]["100.0"][0].update(converged=False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                broken = copy.deepcopy(fit)
                mutate(broken)
                self.assertTrue(response_fit_provenance_errors(broken))

        weighted = copy.deepcopy(fit)
        weighted_records = weighted["inner_cv_convergence"]["100.0"]
        for item, count, loss in zip(weighted_records, (100, 200, 300), (0.1, 0.2, 0.4)):
            item["validation_rows"] = count
            item["fold_logloss"] = loss
        weighted["cv_log_loss"]["100.0"] = (0.1 * 100 + 0.2 * 200 + 0.4 * 300) / 600
        weighted["selected_ridge"] = weighted["ridge"] = 10
        self.assertEqual(response_fit_provenance_errors(weighted), [])
        weighted["cv_log_loss"]["100.0"] = (0.1 + 0.2 + 0.4) / 3
        self.assertIn("cv_pooled_loss_mismatch:100.0", response_fit_provenance_errors(weighted))

    def test_oof_decision_summary_requires_every_channel_and_both_comparators(self) -> None:
        rows = []
        for index in range(50):
            outcome = index % 2
            scored = score_oof_decision(
                outcome=outcome, model_b_probability=0.9 if outcome else 0.1,
                neutral_probability=0.5, v1_probability=0.6 if outcome else 0.4,
            )
            rows.append({
                "family": "bargaining", "role": "player_1", "channel": "bargaining|player_1",
                "outcome": outcome, "model_b_probability": 0.9 if outcome else 0.1,
                "game_id": f"g{index}", "player_model": f"m{index % 12}",
                "config_signature": f"c{index % 6}", "provenance_complete": True,
                "outer_fold": (index % 12) % 3,
                "converged": True, "in_domain": True, **scored,
            })
        report = summarize_oof_decisions(
            rows, axis="model", replicates=20,
            eligible={("bargaining", "bargaining|player_1"): {
                "decisions": 50, "game_ids": {f"g{i}" for i in range(50)},
            }},
        )
        cell = report["cells"]["bargaining|player_1"]
        self.assertTrue(cell["passed"])
        self.assertEqual(cell["outer_fold_cluster_counts"], {"0": 4, "1": 4, "2": 4})
        self.assertLess(cell["comparators"]["neutral"]["log_loss_delta"]["ci_high"], 0.0)
        self.assertLessEqual(cell["comparators"]["v1"]["brier_delta"]["ci_high"], 0.0)
        self.assertIsNotNone(cell["calibration"])
        self.assertFalse(report["all_cells_passed"])
        self.assertFalse(report["cells"]["persuasion|buyer_no"]["reportable"])

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

    def test_crossfit_summary_requires_overall_and_per_fold_cluster_floors(self) -> None:
        def rows(cluster_counts: list[int]) -> list[dict[str, object]]:
            result = []
            for fold, count in enumerate(cluster_counts):
                for index in range(count):
                    for role_index, role in enumerate(("player_1", "player_2") * 3):
                        cluster = f"m{fold}-{index}"
                        result.append({
                            "family": "bargaining", "player_model": cluster,
                            "config_signature": "c", "role": role, "outer_fold": fold,
                            "game_ids": [f"g-{fold}-{index}-{role}-{role_index}"],
                            "fallback_levels": {"exact": 1},
                            "v2_neutral_default_values": 0, "v2_requested_parameter_values": 2,
                            "energy_delta": -1.0, "operational_v1_energy_delta": -1.0,
                            "mean_marginal_crps_delta": 0.0,
                            "mean_operational_v1_marginal_crps_delta": 0.0,
                            "parameter_names": ["x", "y"], "marginal_crps_deltas": [0.0, 0.0],
                            "operational_v1_marginal_crps_deltas": [0.0, 0.0],
                            "observed_rank_values": {"x": 0.2, "y": 0.3},
                            "predictive_moments": {name: {} for name in (
                                "whole_bundle", "conditional_shuffle", "operational_v1")},
                            "support_violations": 0, "nonfinite_draws": 0,
                        })
            return result

        failing = rows([2, 5, 5])
        eligible = {"bargaining": {game for row in failing for game in row["game_ids"]}}
        cell = summarize_validation(
            failing, axis="model", crossfit=True, replicates=10,
            eligible_game_ids_by_family=eligible,
        )["families"]["bargaining"]
        self.assertEqual(cell["outer_fold_cluster_counts"], {"0": 2, "1": 5, "2": 5})
        self.assertEqual(cell["reason"], "crossfit_cluster_floor_failed")

        passing = rows([4, 4, 4])
        eligible = {"bargaining": {game for row in passing for game in row["game_ids"]}}
        cell = summarize_validation(
            passing, axis="model", crossfit=True, replicates=10,
            eligible_game_ids_by_family=eligible,
        )["families"]["bargaining"]
        self.assertTrue(cell["reportable"])

    def test_crossfit_bundle_orchestration_rejects_duplicates_and_pools_by_fold(self) -> None:
        class Router:
            manifest = {"manifest_sha256": "manifest"}

            def route(self, row):
                fold = int(row["assigned_fold"])
                return SimpleNamespace(
                    fold=fold, sha256=f"sha-{fold}", path=Path(f"fold-{fold}.json"),
                    payload={"joint_bundles": {}},
                )

        duplicate = {"bundle_id": "same", "family": "bargaining", "game_ids": []}
        with self.assertRaisesRegex(ValueError, "duplicate OOF"):
            score_crossfit_bundles([duplicate, duplicate], Router())

        rows = [
            {"bundle_id": f"b{fold}", "assigned_fold": fold, "family": "bargaining",
             "game_ids": [f"g{fold}"]}
            for fold in (3, 1, 0, 2)
        ]
        with patch("glee_eval.diagnostics.joint_population.OpponentPopulation", return_value=object()), \
             patch("glee_eval.diagnostics.joint_population.fit_marginals", return_value={}), \
             patch("glee_eval.diagnostics.joint_population.score_observed_bundle") as score:
            score.side_effect = lambda payload, row, **kwargs: {
                "bundle_id": row["bundle_id"], "family": row["family"]
            }
            pooled, eligible, unsupported = score_crossfit_bundles(rows, Router())
        self.assertEqual([row["outer_fold"] for row in pooled], [0, 1, 2, 3])
        self.assertEqual([row["bundle_id"] for row in pooled], ["b0", "b1", "b2", "b3"])
        self.assertEqual(eligible, {"bargaining": {"g0", "g1", "g2", "g3"}})
        self.assertEqual(unsupported, 0)
        self.assertEqual({row["crossfit_manifest_sha256"] for row in pooled}, {"manifest"})

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
