from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from glee_eval.population.opponent_fit import (
    _response_probability,
    _fit_response_coefficients,
    _fit_response_coefficients_coordinate_reference,
    _game_fold,
    _pcg_direction_for_test,
    _sparse_logistic_numerics_for_test,
    _sparse_hvp,
    _armijo_projected_for_test,
    _CompensatedSum,
    _pcg_shift_retry_allowed,
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
    def test_pcg_shift_retry_restriction_is_used_by_production(self) -> None:
        rows=_rows("bargaining|player_1",.5)[:20]
        forbidden={"solved":False,"stop_reason":"iteration_limit","iterations":50,"residual":1.0}
        with patch("glee_eval.population.opponent_fit._pcg_solve",return_value=([0.0,0.0],forbidden)) as solve:
            fit=_fit_response_coefficients(rows,1.0)
        self.assertEqual(solve.call_count,1)
        self.assertEqual(len(fit["contrast_audit"][0]["pcg"][0]["shift_attempts"]),1)
        declared={"solved":False,"stop_reason":"nonpositive_curvature","iterations":1,"residual":1.0}
        with patch("glee_eval.population.opponent_fit._pcg_solve",return_value=([0.0,0.0],declared)) as solve:
            fit=_fit_response_coefficients(rows,1.0)
        self.assertEqual(solve.call_count,6)
        self.assertEqual([a["shift"] for a in fit["contrast_audit"][0]["pcg"][0]["shift_attempts"]],fit["pcg_shift_schedule"])
        self.assertFalse(_pcg_shift_retry_allowed("nonfinite_residual"))
        self.assertFalse(_pcg_shift_retry_allowed("iteration_limit"))
        self.assertTrue(_pcg_shift_retry_allowed("nondescent"))
        self.assertFalse(_pcg_shift_retry_allowed("nonfinite_curvature"))

    def test_compensated_accumulator_cancellation_and_constant_state(self) -> None:
        import math
        values=[1e16,1.0,-1e16,3.0,-3.0]*2000
        accumulator=_CompensatedSum()
        slots_before=len(accumulator.__slots__)
        for value in values: accumulator.add(value)
        self.assertLessEqual(abs(accumulator.value()-math.fsum(values)),1e-12)
        self.assertEqual(len(accumulator.__slots__),slots_before)
        self.assertFalse(hasattr(accumulator,"__dict__"))
        self.assertEqual(accumulator.count,len(values))
        for residual in (0.999e-7, 1.001e-7):
            threshold_values = [1e16, residual, -1e16]
            threshold_accumulator = _CompensatedSum()
            for value in threshold_values:
                threshold_accumulator.add(value)
            reference = math.fsum(threshold_values)
            self.assertAlmostEqual(threshold_accumulator.value(), reference, places=15)
            self.assertEqual(threshold_accumulator.value() <= 1e-7, reference <= 1e-7)

    def test_compensated_solver_is_row_order_deterministic(self) -> None:
        rows=[]
        for x,hits in ((.1,2),(.3,5),(.5,10),(.7,15),(.9,18)):
            for i in range(20): rows.append({"channel":"bargaining|player_1","x":x,"outcome":int(i<hits),"game_id":str(i),"player_model":f"m{i%2}","config_signature":f"c{i%3}"})
        first=_fit_response_coefficients(rows,10.0)
        second=_fit_response_coefficients(list(reversed(rows)),10.0)
        self.assertEqual(first,second)

    def test_sparse_hvp_dense_hessian_and_finite_difference_gradient(self) -> None:
        encoded=[(3,1,{0:1.0,1:-.4}),(2,2,{0:1.0,1:.7})]
        beta=[.2,-.3]; vector=[.6,-.8]
        objective,gradient,hvp=_sparse_logistic_numerics_for_test(encoded,beta,vector)
        dense=[[0.0,0.0],[0.0,0.0]]
        for n,_,f in encoded:
            eta=sum(beta[i]*v for i,v in f.items()); p=1/(1+__import__('math').exp(-eta)); w=n*p*(1-p)
            for i,vi in f.items():
                for j,vj in f.items(): dense[i][j]+=w*vi*vj
        self.assertTrue(__import__('math').isfinite(objective))
        for i in range(2): self.assertAlmostEqual(hvp[i],sum(dense[i][j]*vector[j] for j in range(2)),places=14)
        weights=[]
        for n,_,f in encoded:
            eta=sum(beta[i]*v for i,v in f.items()); p=1/(1+__import__('math').exp(-eta)); weights.append((n*p*(1-p),f))
        shared=_sparse_hvp(vector,weights,0.0,0.0,())
        for i in range(2): self.assertAlmostEqual(shared[i],hvp[i],places=14)
        eps=1e-6
        for i in range(2):
            plus=beta[:]; minus=beta[:]; plus[i]+=eps; minus[i]-=eps
            op=_sparse_logistic_numerics_for_test(encoded,plus,vector)[0]; om=_sparse_logistic_numerics_for_test(encoded,minus,vector)[0]
            self.assertAlmostEqual(gradient[i],(op-om)/(2*eps),places=8)

    def test_pcg_direction_matches_dense_solve_and_guards_curvature(self) -> None:
        matrix=[[4.0,1.0],[1.0,3.0]]; rhs=[1.0,2.0]
        direction,audit=_pcg_direction_for_test(matrix,rhs)
        self.assertTrue(audit["solved"]); self.assertAlmostEqual(direction[0],1/11,places=13); self.assertAlmostEqual(direction[1],7/11,places=13)
        _,bad=_pcg_direction_for_test([[-1.0]],[1.0]); self.assertEqual(bad["stop_reason"],"nonpositive_curvature")
        _,nonfinite=_pcg_direction_for_test([[float("nan")]],[1.0]); self.assertEqual(nonfinite["stop_reason"],"nonfinite_curvature")

    def test_arbitrary_zero_sum_parameterization_preserves_predictor_and_penalty(self) -> None:
        free=[.4,-.1]; original=[*free,-sum(free)]
        self.assertAlmostEqual(sum(original),0.0,places=15)
        for level in range(3):
            features=([1,0] if level==0 else [0,1] if level==1 else [-1,-1])
            self.assertAlmostEqual(sum(free[i]*features[i] for i in range(2)),original[level],places=15)
        self.assertAlmostEqual(sum(v*v for v in original),sum(v*v for v in free)+sum(free)**2,places=15)

    def test_active_bound_near_separation_iteration_limit_and_finite_guards(self) -> None:
        decreasing=[]
        for x,hits in ((.1,9),(.9,1)):
            for i in range(10): decreasing.append({"channel":"bargaining|player_1","x":x,"outcome":int(i<hits),"game_id":str(i),"player_model":"m","config_signature":"c"})
        bounded=_fit_response_coefficients(decreasing,1.0)
        audit=bounded["contrast_audit"][0]
        self.assertTrue(audit["active_slope"]); self.assertTrue(bounded["projected_kkt_pass"]); self.assertLessEqual(audit["raw_kkt_final"],1e-7)
        separated=_fit_response_coefficients(_rows("bargaining|player_1",.5),.1)
        self.assertTrue(all(__import__('math').isfinite(v) for v in separated["coefficients"].values()))
        limited_rows=[]
        for x,hits in ((.1,2),(.3,5),(.5,10),(.7,15),(.9,18)):
            for i in range(20): limited_rows.append({"channel":"bargaining|player_1","x":x,"outcome":int(i<hits),"game_id":str(i),"player_model":f"m{i%2}","config_signature":f"c{i%3}"})
        limited=_fit_response_coefficients(limited_rows,10.0,max_iterations=1,tolerance=1e-15)
        self.assertEqual(limited["stop_reason"],"iteration_limit")
        bad=dict(decreasing[0]); bad["x"]=float("nan")
        with self.assertRaisesRegex(ValueError,"finite x"): _fit_response_coefficients([bad],1.0)
        bad=dict(decreasing[0]); bad["outcome"]=2
        with self.assertRaisesRegex(ValueError,"binary"): _fit_response_coefficients([bad],1.0)

    def test_projected_armijo_failure_and_projection_rhs(self) -> None:
        failed=_armijo_projected_for_test(lambda _:float("nan"),[0.0],[1.0],[-1.0])
        self.assertIsNone(failed[0]); self.assertLess(failed[2],2**-30)
        # Projection makes the proposed bound-coordinate step zero; the RHS
        # therefore uses zero, rather than the unprojected negative direction.
        blocked=_armijo_projected_for_test(lambda x:x[0]**2,[0.0],[-1.0],[1.0],lambda x:[max(0.0,x[0])])
        self.assertIsNone(blocked[0])

    def test_multichannel_raw_kkt_and_top_level_failure_propagation(self) -> None:
        rows=[]
        for channel in ("bargaining|player_1","negotiation|seller"):
            for x,hits in ((.1,2),(.5,5),(.9,8)):
                for i in range(10):
                    rows.append({"channel":channel,"x":x,"outcome":int(i<hits),"game_id":f"{channel}-{i}","player_model":f"m{i%2}","config_signature":f"c{i%3}"})
        fit=_fit_response_coefficients(rows,1.0)
        self.assertTrue(fit["projected_kkt_pass"])
        self.assertEqual(len(fit["contrast_audit"]),2)
        for audit in fit["contrast_audit"]:
            self.assertLessEqual(audit["raw_kkt_final"],fit["projected_kkt_tolerance"])
            self.assertEqual(len(json.loads(audit["free_vector_coefficient_order"])), audit["dimension"])
            self.assertTrue(audit["raw_kkt_worst_key"])
            self.assertAlmostEqual(abs(audit["raw_kkt_worst_value"]),audit["raw_kkt_final"],places=14)
        limited=_fit_response_coefficients(rows,1.0,max_iterations=1,tolerance=1e-15)
        self.assertFalse(limited["projected_kkt_pass"])
        self.assertTrue(any(a["raw_kkt_final"]>limited["tolerance"] for a in limited["contrast_audit"]))

    def test_damped_newton_objective_is_monotone_deterministic_and_converges(self) -> None:
        rows = []
        for x, hits in ((0.1, 2), (0.3, 5), (0.5, 10), (0.7, 15), (0.9, 18)):
            for index in range(20):
                rows.append({"channel": "bargaining|player_1", "x": x, "outcome": int(index < hits),
                             "game_id": f"g{index}", "player_model": "m", "config_signature": "c"})
        first = _fit_response_coefficients(rows, 10.0)
        second = _fit_response_coefficients(list(reversed(rows)), 10.0)
        self.assertTrue(first["converged"])
        self.assertTrue(all(after <= before + 1e-12 for before, after in zip(
            first["objective_history"], first["objective_history"][1:],
        )))
        self.assertEqual(first["coefficients"], second["coefficients"])
        self.assertEqual(
            json.dumps(first["coefficients"], sort_keys=True, separators=(",", ":")),
            json.dumps(second["coefficients"], sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(first["final_objective"], first["objective_history"][-1])
        self.assertTrue(first["projected_kkt_pass"])
        self.assertLessEqual(first["final_max_gradient"], first["projected_kkt_tolerance"])
        self.assertEqual(first["stop_reason"], "projected_kkt")

    def test_sparse_model_offsets_recover_direction_with_ridge_shrinkage(self) -> None:
        rows = []
        for model, hits in (("high", 8), ("low", 2)):
            for index in range(10):
                rows.append({"channel": "persuasion|buyer_yes", "x": None, "outcome": int(index < hits),
                             "game_id": f"{model}-{index}", "player_model": model, "config_signature": "c"})
        fit = _fit_response_coefficients(rows, 10.0)
        high = _response_probability(fit, {"channel": "persuasion|buyer_yes", "x": None,
                                           "player_model": "high", "config_signature": "c"})
        low = _response_probability(fit, {"channel": "persuasion|buyer_yes", "x": None,
                                          "player_model": "low", "config_signature": "c"})
        self.assertGreater(high, low)
        self.assertTrue(all(abs(value) < 2.0 for key, value in fit["coefficients"].items() if key.startswith("model|")))

    def test_mixed_model_config_cross_terms_are_recovered_by_coordinate_newton(self) -> None:
        rows = []
        hits = {("high_model", "high_config"): 9, ("high_model", "low_config"): 7,
                ("low_model", "high_config"): 6, ("low_model", "low_config"): 2}
        for (model, config), positives in hits.items():
            for index in range(10):
                rows.append({"channel": "persuasion|buyer_yes", "x": None, "outcome": int(index < positives),
                             "game_id": f"{model}-{config}-{index}", "player_model": model,
                             "config_signature": config})
        fit = _fit_response_coefficients(rows, 1.0)
        self.assertTrue(fit["projected_kkt_pass"])
        probability = lambda model, config: _response_probability(
            fit, {"channel": "persuasion|buyer_yes", "x": None,
                  "player_model": model, "config_signature": config})
        self.assertGreater(probability("high_model", "low_config"), probability("low_model", "low_config"))
        self.assertGreater(probability("low_model", "high_config"), probability("low_model", "low_config"))

    def test_newton_pcg_matches_converged_reference_objective_and_zero_sum_gauge(self) -> None:
        rows = []
        for x, hits in ((0.1, 2), (0.3, 5), (0.5, 10), (0.7, 15), (0.9, 18)):
            for index in range(20):
                rows.append({"channel": "bargaining|player_1", "x": x, "outcome": int(index < hits),
                             "game_id": f"g{index}", "player_model": f"m{index % 2}",
                             "config_signature": f"c{index % 3}"})
        pcg = _fit_response_coefficients(rows, 10.0)
        reference = _fit_response_coefficients_coordinate_reference(rows, 10.0)
        self.assertTrue(pcg["projected_kkt_pass"] and reference["projected_kkt_pass"])
        self.assertAlmostEqual(pcg["final_objective"], reference["final_objective"], places=10)
        for key in pcg["coefficients"]:
            self.assertAlmostEqual(pcg["coefficients"][key], reference["coefficients"][key], places=8)
        audit = pcg["contrast_audit"][0]
        self.assertAlmostEqual(audit["zero_sum_model"], 0.0, places=14)
        self.assertAlmostEqual(audit["zero_sum_config"], 0.0, places=14)
        self.assertEqual(pcg["optimizer"], "zero_sum_sparse_newton_pcg_with_armijo")
        self.assertTrue(all(record["solved"] for record in audit["pcg"]))
        self.assertEqual(pcg["pcg_shift_schedule"], [0.0, 1e-12, 1e-10, 1e-8, 1e-6, 1e-4])
        self.assertEqual(pcg["pcg_preconditioner"], "exact_intercept_slope_block_plus_diagonal_contrasts")
        self.assertEqual(pcg["pcg_residual_rule"], "max(1e-12,min(.5,sqrt(current_projected_kkt))*current_projected_kkt)")
        self.assertEqual(pcg["pcg_iteration_cap_rule"], "min(2000,max(50,4*free_parameter_count))")
        for record in audit["pcg"]:
            expected_target = max(1e-12, min(.5, record["current_projected_kkt"] ** .5) * record["current_projected_kkt"])
            self.assertEqual(record["absolute_residual_target"], expected_target)
            self.assertEqual(record["iteration_cap"], min(2000, max(50, 4 * audit["dimension"])))
            self.assertLessEqual(record["final_residual"], record["absolute_residual_target"])
            self.assertGreater(record["curvature_product"], 0.0)
            self.assertLess(record["descent_product"], 0.0)

    def test_nonconverged_inner_fold_disqualifies_ridge(self) -> None:
        rows = _rows("bargaining|player_1", 0.5)
        failed_fit = {"converged": False, "stop_reason": "iteration_limit", "final_max_gradient": 1.0,
                      "projected_kkt_tolerance": 1e-7, "projected_kkt_pass": False, "iterations": 300}
        with patch("glee_eval.population.opponent_fit._fit_response_coefficients", return_value=failed_fit):
            fit = fit_hierarchical_responses(rows, ridge_grid=(1.0,))
        self.assertEqual(fit["status"], "unavailable")
        self.assertEqual(fit["reason"], "no_ridge_with_all_inner_folds_converged")
        records = fit["inner_cv_convergence"]["1.0"]
        self.assertEqual([record["fold"] for record in records], [0, 1, 2])
        self.assertTrue(all(not record["converged"] and not record["projected_kkt_pass"] for record in records))
        self.assertTrue(all(record["fold_logloss"] == float("inf") for record in records))
        self.assertEqual(fit["eligible_ridges"], [])

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
        self.assertTrue(fit["eligible_ridges"])
        selected_records = fit["inner_cv_convergence"][str(fit["selected_ridge"])]
        self.assertEqual(len(selected_records), 3)
        self.assertTrue(all(record["converged"] and record["projected_kkt_pass"]
                            and record["finite_validation_probability"]
                            and record["finite_validation_loss"] for record in selected_records))
        self.assertEqual(fit["ridge_tie_rule"], "minimum pooled validation-decision logloss; exact ties choose larger ridge")
        self.assertIn("converged", provenance)
        self.assertIn("final_objective", provenance)
        self.assertIn("final_max_gradient", provenance)

    def test_cv_logloss_is_pooled_over_unequal_fold_sizes(self) -> None:
        game_ids = {fold: [] for fold in range(3)}
        candidate = 0
        targets = {0: 10, 1: 20, 2: 30}
        while any(len(game_ids[fold]) < targets[fold] for fold in range(3)):
            game = f"unequal-{candidate}"
            fold = _game_fold(game)
            if len(game_ids[fold]) < targets[fold]:
                game_ids[fold].append(game)
            candidate += 1
        rows = []
        rates = {0: 0.2, 1: 0.5, 2: 0.8}
        for fold, games in game_ids.items():
            positives = int(round(10 * rates[fold]))
            for game_index, game in enumerate(games):
                for index in range(10):
                    rows.append({"channel": "persuasion|buyer_yes", "x": None,
                                 "outcome": int(index < positives), "game_id": game,
                                 "player_model": f"m{game_index % 4}",
                                 "config_signature": f"c{game_index % 5}"})
        fit = fit_hierarchical_responses(rows, ridge_grid=(10.0,))
        records = fit["inner_cv_convergence"]["10.0"]
        pooled = sum(record["fold_logloss"] * record["validation_rows"] for record in records) / sum(
            record["validation_rows"] for record in records)
        unweighted = sum(record["fold_logloss"] for record in records) / 3
        self.assertAlmostEqual(fit["cv_log_loss"]["10.0"], pooled, places=15)
        self.assertNotAlmostEqual(pooled, unweighted, places=6)

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
            for index in range(15)
        ]
        manifest = build_manifest(events)
        excluded_fold = 1
        rows = extract_response_observations(
            events, crossfit_manifest=manifest, excluded_fold=excluded_fold, crossfit_axis="actor",
        )
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["decision_id"] for row in rows}), 10)
        self.assertTrue(all(row_fold(row, "actor", manifest) != excluded_fold for row in rows))
        expected_config_fold = row_fold(events[0], "config", manifest)
        self.assertTrue(all(row_fold(row, "config", manifest) == expected_config_fold for row in rows))
        self.assertTrue(all("configuration" in row and "player_2_model" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
