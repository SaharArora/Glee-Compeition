from __future__ import annotations

import unittest
import json
import tempfile
import copy
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from functools import lru_cache

from glee_eval.population.opponent_fit import fit_hierarchical_responses
from glee_eval.storage.trajectories import canonical_json_sha256

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
    response_reference_errors,
    transform_parameters,
)


@lru_cache(maxsize=1)
def _actual_response_fit():
    rows = []
    for game in range(30):
        for index in range(6):
            rows.append({
                "channel": "persuasion|buyer_yes", "x": None,
                "outcome": int(index < (1 + game % 5)), "game_id": f"game-{game}",
                "player_model": f"model-{game % 3}", "config_signature": f"config-{game % 4}",
            })
    fit = fit_hierarchical_responses(rows)
    if fit.get("status") != "ok":
        raise AssertionError(f"actual response fixture did not converge: {fit.get('reason')}")
    return fit


class JointPopulationValidationTests(unittest.TestCase):
    def test_compact_response_references_validate_recompute_and_detect_tampering(self) -> None:
        fit=copy.deepcopy(_actual_response_fit())
        fit_hash=canonical_json_sha256(fit)
        value,_=__import__('glee_eval.population.opponent_fit',fromlist=['response_parameter']).response_parameter(
            fit,channel="persuasion|buyer_yes",player_model="model-0",signature="config-0")
        support=fit["channel_support"]["persuasion|buyer_yes"]
        entries={
            "trust_prior":{"family":"persuasion","channel":"persuasion|buyer_yes","canonical_fit_reference":"joint_model.response_estimators.persuasion","canonical_fit_sha256":fit_hash,"parameter_kind":"probability","channel_support":support},
            "buy_after_no_rate":{"family":"persuasion","channel":"persuasion|buyer_no","canonical_fit_reference":"joint_model.response_estimators.persuasion","canonical_fit_sha256":fit_hash,"channel_support":None},
        }
        payload={"joint_model":{"response_estimators":{"bargaining":copy.deepcopy(fit),"negotiation":copy.deepcopy(fit),"persuasion":fit},"response_estimator_reference_schema":{"version":1,"canonical_root":"joint_model.response_estimators","required_fields":["family","channel","canonical_fit_reference","canonical_fit_sha256"],"canonical_fit_sha256_by_family":{"bargaining":fit_hash,"negotiation":fit_hash,"persuasion":fit_hash},"references_by_family":{"bargaining":0,"negotiation":0,"persuasion":2},"total_references":2,"canonical_full_fit_count":3}},"joint_bundles":{"bargaining":[],"negotiation":[],"persuasion":[{"bundle_id":"b","family":"persuasion","role":"buyer","player_model":"model-0","config_signature":"config-0","parameters":{"trust_prior":value},"response_estimator":entries}]}}
        self.assertEqual(response_reference_errors(payload),[])
        for field,bad in (("family","bargaining"),("channel","persuasion|seller_high"),("canonical_fit_reference","wrong")):
            tampered=copy.deepcopy(payload); tampered["joint_bundles"]["persuasion"][0]["response_estimator"]["trust_prior"][field]=bad
            self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); tampered["joint_bundles"]["persuasion"][0]["parameters"]["trust_prior"]+=.1
        self.assertTrue(any("recompute" in error for error in response_reference_errors(tampered)))
        tampered=copy.deepcopy(payload); del tampered["joint_bundles"]["persuasion"][0]["response_estimator"]["buy_after_no_rate"]
        self.assertTrue(any("completeness" in error for error in response_reference_errors(tampered)))
        for schema_field,bad in (("version",2),("canonical_root","wrong"),("required_fields",[])):
            tampered=copy.deepcopy(payload); tampered["joint_model"]["response_estimator_reference_schema"][schema_field]=bad
            self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); tampered["joint_model"]["response_estimators"]["persuasion"]["tolerance"]=9
        self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); del tampered["joint_model"]["response_estimator_reference_schema"]
        self.assertEqual(response_reference_errors(tampered),[])
        self.assertEqual(response_reference_errors(tampered,require_schema=True),["missing_reference_schema"])
        tampered=copy.deepcopy(payload); tampered["joint_model"]["response_estimator_reference_schema"]["extra"]=True
        self.assertEqual(response_reference_errors(tampered),["reference_schema_keys"])
        tampered=copy.deepcopy(payload); tampered["joint_model"]["response_estimators"]["extra"]={}
        self.assertEqual(response_reference_errors(tampered),["canonical_fit_families"])
        for field in ("parameter_kind","channel_support"):
            tampered=copy.deepcopy(payload); tampered["joint_bundles"]["persuasion"][0]["response_estimator"]["trust_prior"][field]="tampered"
            self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); del tampered["joint_bundles"]["persuasion"][0]["response_estimator"]["buy_after_no_rate"]["channel_support"]
        self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); tampered["joint_bundles"]["persuasion"][0]["response_estimator"]["trust_prior"]["contrast_audit"]={}
        self.assertTrue(response_reference_errors(tampered))
        tampered=copy.deepcopy(payload); tampered["joint_bundles"]["persuasion"][0]["parameters"]["buy_after_no_rate"]=None
        self.assertTrue(any("parameter_presence" in error for error in response_reference_errors(tampered)))
        tampered=copy.deepcopy(payload)
        tampered["joint_bundles"]["persuasion"][0]["parameters"]["trust_prior"]=math.nextafter(value,math.inf)
        self.assertTrue(any("recompute" in error for error in response_reference_errors(tampered)))

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
        fit = copy.deepcopy(_actual_response_fit())

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
        fit = copy.deepcopy(_actual_response_fit())
        self.assertEqual(response_fit_provenance_errors(fit), [])

        mutations = {
            "kkt": lambda item: item.update(final_max_gradient=2e-7),
            "stagnation": lambda item: item.update(stop_reason="line_search_stagnation"),
            "slope": lambda item: item["coefficients"].update({"slope|x": 0.0}),
            "objective": lambda item: item.update(objective_history=[1.0, 1.1, 0.5]),
            "selection": lambda item: item.update(selected_ridge=10, ridge=10),
            "nonfinite": lambda item: item["coefficients"].update({"intercept|x": float("nan")}),
            "inner": lambda item: item["inner_cv_convergence"][str(item["selected_ridge"])][0].update(converged=False),
            "old_optimizer": lambda item: item.update(
                optimizer="sparse_coordinate_newton_with_deterministic_backtracking"),
            "order_hash": lambda item: item["contrast_audit"][0].update(coefficient_order_sha256="bad"),
            "zero_sum": lambda item: item["contrast_audit"][0].update(zero_sum_model=1e-4),
            "pcg_target": lambda item: item["contrast_audit"][0]["pcg"][0].update(
                absolute_residual_target=999.0),
            "undeclared_shift_retry": lambda item: item["contrast_audit"][0]["pcg"][0][
                "shift_attempts"
            ][0].update(curvature_failure="iteration_limit"),
            "armijo": lambda item: item["contrast_audit"][0]["armijo"][0].update(passed=False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                broken = copy.deepcopy(fit)
                mutate(broken)
                self.assertTrue(response_fit_provenance_errors(broken))

        weighted = copy.deepcopy(fit)
        selected_key = str(weighted["selected_ridge"])
        weighted["cv_log_loss"][selected_key] += 0.01
        self.assertIn(
            f"cv_pooled_loss_mismatch:{selected_key}", response_fit_provenance_errors(weighted)
        )

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
