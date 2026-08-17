from __future__ import annotations

import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from glee_eval.diagnostics.bargaining_model_a_campaign_v2 import REQUIRED_AUDIT_CHECKS, verify_audit_v2
from glee_eval.diagnostics.bargaining_model_a_evaluator_v2 import (
    _complete_trajectory_rows,
    jordan_reached_diagnostics,
)
from glee_eval.diagnostics.operational_v1_bargaining import OperationalV1BargainingComparator
from glee_eval.opponents.policies import BargainingPolicy
from glee_eval.population.bargaining_model_a_v2 import (
    VisibilityViolation,
    aggregate_inner_game_objective,
    extract_event_row_v2,
    iter_extracted_rows_v2,
)
from glee_eval.population.opponent_fit import ARCHETYPE_BANDS


def quantiles(low: float, high: float) -> dict[str, float]:
    return {f"{index / 100:.2f}": low + (high - low) * (index - 1) / 98 for index in range(1, 100)}


def event(
    game_id: str = "g1", *, role: str = "player_1", round_number: int = 1,
    action: str = "offer", history: list[dict] | None = None, complete: bool = True,
) -> dict:
    public = {
        "money_to_divide": 100,
        "max_rounds": 6,
        "complete_information": complete,
        "messages_allowed": False,
    }
    if complete:
        public.update({"delta_1": 0.9, "delta_2": 0.95})
    return {
        "event_id": "",
        "game_id": game_id,
        "game_family": "bargaining",
        "source": "synthetic_v2_test",
        "configuration": {**public, "private_future_value": 999},
        "public_parameters": public,
        "player_1_model": "actor-p1",
        "player_2_model": "actor-p2",
        "role": role,
        "round": round_number,
        "action_type": "offer" if action == "offer" else "decision",
        "numeric_action": 60 if action == "offer" else None,
        "accepted": action == "accept",
        "rejected": action == "reject",
        "raw_record": {"decision": action if action != "offer" else None},
        "transcript_so_far": history or [],
        "terminal_outcome": {"secret": "future"},
        "player_payoff": 123456,
    }


def offer_history(round_number: int = 1) -> dict:
    return {
        "round": round_number,
        "role": "player_1",
        "action_type": "offer",
        "numeric_action": 60,
        "raw": {"self_gain": 60, "other_gain": 40},
    }


class StrictVisibilityAndIdentityTests(unittest.TestCase):
    def test_future_and_same_actor_current_round_canaries_fail_closed(self) -> None:
        future = event(role="player_2", action="reject", history=[offer_history(99)])
        with self.assertRaises(VisibilityViolation):
            extract_event_row_v2(future)
        same_actor = event(role="player_1", action="reject", history=[offer_history(1)])
        with self.assertRaises(VisibilityViolation):
            extract_event_row_v2(same_actor)

    def test_private_configuration_fallback_is_forbidden(self) -> None:
        poisoned = event(complete=False)
        poisoned["public_parameters"] = {}
        with self.assertRaises(VisibilityViolation):
            extract_event_row_v2(poisoned)

    def test_private_and_terminal_poison_do_not_change_features_or_identity(self) -> None:
        left = event(complete=False)
        right = copy.deepcopy(left)
        right["configuration"].update({"delta_1": -999, "delta_2": 999, "private_future_value": "changed"})
        right["terminal_outcome"] = {"secret": "different"}
        right["player_payoff"] = -999999
        left_row, right_row = extract_event_row_v2(left), extract_event_row_v2(right)
        assert left_row and right_row
        self.assertEqual(left_row["features_base"], right_row["features_base"])
        self.assertEqual(left_row["config_key"], right_row["config_key"])
        self.assertEqual(left_row["row_id"], right_row["row_id"])

    def test_row_identity_is_content_derived_and_duplicate_rejected(self) -> None:
        original = event()
        changed_id = copy.deepcopy(original)
        changed_id["event_id"] = "arbitrary-observational-id"
        first, second = extract_event_row_v2(original), extract_event_row_v2(changed_id)
        assert first and second
        self.assertEqual(first["row_id"], second["row_id"])
        self.assertEqual(len(first["row_id"]), 64)
        with self.assertRaisesRegex(VisibilityViolation, "duplicate content-derived row_id"):
            list(iter_extracted_rows_v2([original, changed_id]))

    def test_missing_callback_is_explicitly_right_censored(self) -> None:
        [row] = list(iter_extracted_rows_v2([event()]))
        self.assertIsNone(row["stop"])
        self.assertFalse(row["trajectory_observed"])
        self.assertIn("right_censored", row["trajectory_censor_reason"])


class ComparatorAndObjectiveTests(unittest.TestCase):
    def test_operational_comparator_executes_exact_policy_and_retains_archetype(self) -> None:
        payload = {
            "schema_version": 1,
            "archetype_bands": {name: list(bounds) for name, bounds in ARCHETYPE_BANDS.items()},
            "inverted_parameters": ["concession_rate", "accept_margin", "trust_prior"],
            "families": {"bargaining": {
                "target_share": quantiles(0.48, 0.66),
                "accept_threshold": quantiles(0.40, 0.50),
                "concession_rate": quantiles(-0.05, 0.12),
            }},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "population.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            comparator = OperationalV1BargainingComparator(path, draws=256, seed=20260817)
            target = event(round_number=3)
            target["transcript_so_far"] = [
                offer_history(1),
                {"round": 1, "role": "player_2", "action_type": "decision", "raw": {"decision": "reject"}},
            ]
            row = extract_event_row_v2(target)
            assert row is not None
            prediction = comparator.predict(row)
            state = comparator.state_for(row)
            direct = [BargainingPolicy(spec).decide(state).numeric_action / 100 for spec in comparator.specs]
            self.assertEqual(prediction["offer_samples"], direct)
            boulware = [
                (spec, value) for spec, value in zip(comparator.specs, direct)
                if spec.archetype == "boulware"
            ]
            self.assertTrue(boulware)
            for spec, value in boulware:
                # Round 3 is before 75% of horizon 6, so exact policy freezes.
                expected = min(0.95, max(0.05, float(spec.parameters["target_share"]) + random.Random(spec.seed + 3).uniform(
                    -float(spec.parameters["action_noise"]), float(spec.parameters["action_noise"]),
                )))
                self.assertAlmostEqual(value, round(100 * expected, 2) / 100)

    def test_inner_cv_weights_games_not_unequal_fold_means(self) -> None:
        folds = [
            {"g1": {"joint_loss": 0.0}},
            {f"g{index}": {"joint_loss": 1.0} for index in range(2, 11)},
            {},
        ]
        self.assertAlmostEqual(aggregate_inner_game_objective(folds), 0.9)
        self.assertNotEqual(aggregate_inner_game_objective(folds), 0.5)

    def test_censored_game_is_not_assigned_a_terminal_endpoint(self) -> None:
        complete = [
            {"game_id": "complete", "role": "player_1", "round": 1, "row_id": "a", "actor_hash": "a", "config_hash": "c", "trajectory_observed": True, "stop_outcome": 0, "candidate_stop": 0.1, "v1_stop": 0.2, "simple_stop": 0.2},
            {"game_id": "complete", "role": "player_1", "round": 2, "row_id": "b", "actor_hash": "a", "config_hash": "c", "trajectory_observed": True, "stop_outcome": 1, "candidate_stop": 0.8, "v1_stop": 0.7, "simple_stop": 0.5},
        ]
        censored = [
            {"game_id": "censored", "role": "player_1", "round": 1, "row_id": "c", "actor_hash": "a", "config_hash": "c", "trajectory_observed": False, "stop_outcome": 0, "candidate_stop": 0.1, "v1_stop": 0.2, "simple_stop": 0.2},
        ]
        rows, diagnostics = _complete_trajectory_rows(complete + censored, "player_1")
        self.assertEqual([row["game_id"] for row in rows], ["complete"])
        self.assertEqual(diagnostics, {"complete_games": 1, "right_censored_games": 1, "invalid_games": 0})


class AuditAndJordanDiagnosticsTests(unittest.TestCase):
    def test_audit_gate_rejects_minimal_pass_and_nonpassing_check(self) -> None:
        contract = {"locked_code": {"x": "a" * 64}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(json.dumps({"schema": "glee.wave5d.bargaining_model_a_v2_prefit_audit.v1", "verdict": "pass"}))
            with self.assertRaises(PermissionError):
                verify_audit_v2(path, "b" * 64, contract)
            payload = {
                "schema": "glee.wave5d.bargaining_model_a_v2_prefit_audit.v1",
                "verdict": "pass", "contract_sha256": "b" * 64,
                "audited_commit": "c" * 40, "reviewed_code_sha256": contract["locked_code"],
                "auditor_id": "independent", "auditor_fresh_context": True,
                "auditor_implemented_route_2": False, "reviewed_test_command": "tests",
                "reviewed_test_result": "pass", "checks": {name: "pass" for name in REQUIRED_AUDIT_CHECKS},
                "objections": [], "notes": "", "structural_outcomes_inspected": False,
                "authorization": "prefit_go_eligible_root_token_still_required",
            }
            payload["checks"][REQUIRED_AUDIT_CHECKS[0]] = "fail"
            path.write_text(json.dumps(payload))
            with self.assertRaises(PermissionError):
                verify_audit_v2(path, "b" * 64, contract)

    def test_jordan_reached_branches_are_exact_and_diagnostic_only(self) -> None:
        summaries = []
        for axis in ("actor", "config"):
            summaries.append({
                "axis": axis,
                "role_channel_cells": [
                    {"role": "player_1", "channel": "offer", "candidate_central_80_coverage": 0.8, "candidate_minus_v1_mae": -0.01},
                    {"role": "player_2", "channel": "offer", "candidate_central_80_coverage": 0.8, "candidate_minus_v1_mae": -0.01},
                ],
            })
        result = jordan_reached_diagnostics(summaries)
        self.assertEqual(
            [record["immutable_label"] for record in result["records"]],
            [
                "bargaining/player_1/offer/coverage_low",
                "bargaining/player_2/offer/coverage_low",
                "bargaining/player_2/offer/mae_high",
            ],
        )
        self.assertTrue(result["all_pass"])
        self.assertFalse(result["live_evidence_claimed"])


if __name__ == "__main__":
    unittest.main()
