from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from glee_eval.diagnostics.bargaining_model_a_campaign import _verify_audit, _verify_contract
from glee_eval.diagnostics.bargaining_model_a_evaluator import (
    categorical_brier,
    categorical_log_loss,
    empirical_crps,
    expected_calibration_error,
)
from glee_eval.population.bargaining_model_a import (
    ACTION_CLASSES,
    ROLES,
    action_probabilities,
    build_bargaining_manifest,
    extract_event_row,
    fit_role_model,
    fold_for_row,
    inner_fold,
    iter_extracted_rows,
    predict_role_model,
)


def event(
    game_id: str,
    *,
    actor: str,
    role: str,
    round_number: int,
    action: str,
    transcript: list[dict] | None = None,
    complete: bool = True,
    accepted: bool = False,
    rejected: bool = False,
    share: float = 0.6,
    config_variant: int = 0,
) -> dict:
    config = {
        "money_to_divide": 100,
        "max_rounds": 4 + config_variant,
        "complete_information": complete,
        "messages_allowed": False,
    }
    if complete:
        config.update({"delta_1": 0.9, "delta_2": 0.95})
    return {
        "event_id": f"{game_id}-{round_number}-{role}-{action}",
        "game_id": game_id,
        "game_family": "bargaining",
        "source": "synthetic_test",
        "configuration": config,
        "public_parameters": config,
        "config_id": f"cfg-{config_variant}",
        "player_1_model": actor if role == "player_1" else "other-p1",
        "player_2_model": actor if role == "player_2" else "other-p2",
        "role": role,
        "round": round_number,
        "action_type": "offer" if action == "offer" else "decision",
        "numeric_action": share * 100 if action == "offer" else None,
        "accepted": accepted,
        "rejected": rejected,
        "transcript_so_far": transcript or [],
        # Deliberate poison pills: extraction must never use either as a feature.
        "terminal_outcome": {"result": "secret_future", "agreement_round": 99},
        "player_payoff": 123456,
        "opponent_payoff": -123456,
        "raw_record": {"decision": action if action != "offer" else None},
    }


def synthetic_rows(count: int = 48, role: str = "player_1") -> list[dict]:
    rows = []
    for index in range(count):
        actor = f"actor-{index % 15:02d}"
        action = "offer" if index % 3 == 0 else "accept" if index % 3 == 1 else "reject"
        transcript = []
        if action != "offer":
            transcript = [{
                "role": "player_2" if role == "player_1" else "player_1",
                "player": "Bob",
                "round": 1,
                "action_type": "offer",
                "raw": {"player": "Bob", "bob_gain": 55, "alice_gain": 45},
            }]
        row = extract_event_row(event(
            f"g-{role}-{index}",
            actor=actor,
            role=role,
            round_number=1 + index % 4,
            action=action,
            transcript=transcript,
            accepted=action == "accept",
            rejected=action == "reject",
            share=0.45 + 0.01 * (index % 10),
            config_variant=index % 7,
        ))
        assert row is not None
        row["stop"] = int(action == "accept" or row["round"] >= row["max_rounds"])
        rows.append(row)
    return rows


class BargainingModelAExtractionTests(unittest.TestCase):
    def test_extraction_uses_only_visible_state_and_hides_incomplete_deltas(self) -> None:
        row = extract_event_row(event(
            "g1",
            actor="actor-00",
            role="player_1",
            round_number=1,
            action="offer",
            complete=False,
        ))
        self.assertIsNotNone(row)
        assert row is not None
        serialized_features = str(row["features_base"])
        self.assertNotIn("secret_future", serialized_features)
        self.assertNotIn("123456", serialized_features)
        self.assertEqual(row["features_base"]["delta_1"], 0.0)
        self.assertEqual(row["features_base"]["delta_1_missing"], 1.0)
        self.assertEqual(row["features_base"]["delta_2_missing"], 1.0)

    def test_missing_callback_before_horizon_is_censored_not_rejected(self) -> None:
        rows = list(iter_extracted_rows([
            event("g1", actor="actor-00", role="player_1", round_number=1, action="offer"),
        ]))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["stop"])
        self.assertEqual(rows[0]["stop_censor_reason"], "missing_terminal_callback_before_horizon")
        self.assertEqual(rows[0]["action_class"], "offer")

    def test_accept_is_observed_stop(self) -> None:
        offer = event("g1", actor="actor-00", role="player_1", round_number=1, action="offer")
        transcript = [{
            "role": "player_1",
            "player": "Alice",
            "round": 1,
            "action_type": "offer",
            "raw": {"player": "Alice", "alice_gain": 60, "bob_gain": 40},
        }]
        accept = event(
            "g1", actor="actor-01", role="player_2", round_number=1,
            action="accept", transcript=transcript, accepted=True,
        )
        rows = list(iter_extracted_rows([offer, accept]))
        self.assertEqual([row["stop"] for row in rows], [0, 1])
        self.assertEqual(rows[1]["action_class"], "accept")


class BargainingModelAFoldAndFitTests(unittest.TestCase):
    def test_actor_manifest_has_three_disjoint_folds_of_five(self) -> None:
        rows = synthetic_rows(60, "player_1") + synthetic_rows(60, "player_2")
        manifest = build_bargaining_manifest(rows)
        assignments = manifest["actor_identity_hashes"]
        self.assertEqual(len(assignments), 15)
        self.assertEqual(sorted(assignments.values()).count(0), 5)
        self.assertEqual(sorted(assignments.values()).count(1), 5)
        self.assertEqual(sorted(assignments.values()).count(2), 5)
        for row in rows:
            self.assertIn(fold_for_row(row, "actor", manifest), {0, 1, 2})

    def test_inner_fold_is_deterministic(self) -> None:
        self.assertEqual(inner_fold("same-game"), inner_fold("same-game"))
        self.assertIn(inner_fold("same-game"), {0, 1, 2})

    def test_factorized_probabilities_are_coherent(self) -> None:
        rows = synthetic_rows(72, "player_1")
        model = fit_role_model(rows, ridge=10.0, history_window=1, residual_bins=32)
        prediction = predict_role_model(model, rows[0])
        self.assertIsNotNone(prediction["action"])
        assert prediction["action"] is not None
        self.assertEqual(set(prediction["action"]), set(ACTION_CLASSES))
        self.assertAlmostEqual(sum(prediction["action"].values()), 1.0, places=12)
        self.assertTrue(all(0.0 < value < 1.0 for value in prediction["action"].values()))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in prediction["offer_samples"]))

    def test_unseen_actor_and_config_receive_no_serialized_effect(self) -> None:
        training = synthetic_rows(45, "player_1")
        model = fit_role_model(training, ridge=100.0, history_window=1, residual_bins=32)
        unseen = synthetic_rows(1, "player_1")[0]
        unseen["actor_model"] = "never-seen"
        unseen["config_key"] = "never-seen-config"
        action = action_probabilities(model["heads"], unseen, model["spec"])
        self.assertIsNotNone(action)
        for head in model["heads"].values():
            if head.get("coefficients"):
                self.assertNotIn("actor|never-seen", head["coefficients"])
                self.assertNotIn("config|never-seen-config", head["coefficients"])


class BargainingModelAMetricAndGuardTests(unittest.TestCase):
    def test_crps_and_proper_discrete_scores(self) -> None:
        samples = [0.1, 0.4, 0.9]
        observation = 0.5
        direct = sum(abs(value - observation) for value in samples) / len(samples)
        direct -= 0.5 * sum(abs(left - right) for left in samples for right in samples) / len(samples) ** 2
        self.assertAlmostEqual(empirical_crps(samples, observation), direct, places=15)
        perfect = {label: (1.0 if label == "accept" else 0.0) for label in ACTION_CLASSES}
        diffuse = {label: 0.25 for label in ACTION_CLASSES}
        self.assertLess(categorical_log_loss(perfect, "accept"), categorical_log_loss(diffuse, "accept"))
        self.assertLess(categorical_brier(perfect, "accept"), categorical_brier(diffuse, "accept"))

    def test_ece_is_zero_for_matching_bins(self) -> None:
        probabilities = [0.25] * 4 + [0.75] * 4
        outcomes = [1, 0, 0, 0, 1, 1, 1, 0]
        self.assertAlmostEqual(expected_calibration_error(probabilities, outcomes), 0.0)

    def test_runner_refuses_pending_prefit_audit(self) -> None:
        contract = Path(__file__).resolve().parents[1] / "research" / "ROUTES" / "WAVE5C_MODEL_A_PREFIT_CONTRACT.json"
        payload, digest = _verify_contract(contract)
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "audit.json"
            audit.write_text('{"schema":"glee.wave5c.bargaining_model_a_prefit_audit.v1","verdict":"pending"}\n')
            with self.assertRaises(PermissionError):
                _verify_audit(audit, digest, payload)


if __name__ == "__main__":
    unittest.main()
