from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.data.schemas import GameState, to_jsonable
from glee_eval.live import fixtures as live_fixtures
from glee_eval.live.schema import negotiation_scale, to_game_state, to_live_action
from glee_eval.live.strategy import LiveStrategy
from glee_eval.response_models.runtime import bargaining_keys
from research.CANDIDATES.r1_treatment_off_baseline import (
    BOUND_COMMIT,
    FACTORIAL_SLOTS,
    TREATMENT_OFF_WRAPPERS,
    Factorial01Wrapper,
    Factorial10Wrapper,
    TreatmentOffEconomicCore,
)


MASTER_SEED = 20260829


def _canonical(value) -> bytes:
    return json.dumps(
        to_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _state(
    family: str,
    role: str,
    kind: str,
    *,
    transcript: list[dict] | None = None,
) -> GameState:
    if family == "bargaining":
        public = {
            "money_to_divide": 100.0,
            "delta_1": 0.99,
            "delta_2": 0.80,
            "complete_information": True,
            "messages_allowed": True,
            "max_rounds": 6,
        }
        private = {"delta_1": 0.99, "delta_2": 0.80}
        if transcript is None and kind == "decision":
            other = "player_2" if role == "player_1" else "player_1"
            transcript = [
                {
                    "round": 3,
                    "role": other,
                    "action_type": "offer",
                    "numeric_action": 60.0,
                    "self_gain": 60.0,
                    "other_gain": 40.0,
                    "structured": {"self_gain": 60.0, "other_gain": 40.0},
                }
            ]
    elif family == "negotiation":
        public = {
            "product_price_order": 1000.0,
            "seller_value": 0.80,
            "buyer_value": 1.20,
            "complete_information": True,
            "messages_allowed": True,
            "max_rounds": 8,
        }
        private = {"seller_value": 0.80, "buyer_value": 1.20}
        if transcript is None and kind == "decision":
            other = "buyer" if role == "seller" else "seller"
            price = 850.0 if role == "seller" else 1150.0
            transcript = [
                {
                    "round": 3,
                    "role": other,
                    "action_type": "offer",
                    "numeric_action": price,
                    "structured": {"product_price": price},
                }
            ]
    else:
        public = {
            "product_price": 100.0,
            "p": 0.60,
            "v": 1.40,
            "c": 0.20,
            "total_rounds": 20,
            "seller_message_type": "binary",
            "is_seller_know_cv": True,
            "is_myopic": False,
        }
        private = {}
        if transcript is None and role == "buyer":
            transcript = [
                {
                    "round": 3,
                    "role": "seller",
                    "action_type": "recommendation",
                    "buy_no_buy": "yes",
                    "structured": {"decision": "yes"},
                    "free_text_message": "yes",
                }
            ]
    metadata = {"quality": "high-quality"} if family == "persuasion" and role == "seller" else {}
    return GameState(
        scenario_id=f"r1-{family}-{role}-{kind}",
        game_id=f"r1-{family}-{role}-{kind}",
        game_family=family,
        role=role,
        round=3,
        horizon=20 if family == "persuasion" else 8,
        public_parameters=public,
        private_parameters=private,
        visible_transcript=list(transcript or []),
        valid_action_schema={"kind": kind},
        metadata=metadata,
    )


def _all_family_role_action_states() -> list[GameState]:
    return [
        *(
            _state("bargaining", role, kind)
            for role in ("player_1", "player_2")
            for kind in ("offer", "decision")
        ),
        *(
            _state("negotiation", role, kind)
            for role in ("seller", "buyer")
            for kind in ("offer", "decision")
        ),
        _state("persuasion", "seller", "recommendation"),
        _state("persuasion", "buyer", "buy_decision"),
    ]


def _response_payload(state: GameState) -> dict:
    buckets = {}
    for index in range(7):
        self_share = round(0.50 + index * 0.02, 2)
        key = bargaining_keys(state, "player_2", 1.0 - self_share)[0]
        buckets[key] = {
            "probability": 1.0 if self_share == 0.56 else 0.50,
            "trials": 100,
            "uncertainty": 0.0,
            "support_quality": 1.0,
            "theory_residual": {"count": 100, "mean": 0.0, "min": 0.0, "max": 0.0},
        }
    return {
        "version": 1,
        "min_support": 1,
        "families": {
            "bargaining": {"global_rate": 0.5, "global_trials": 100, "buckets": buckets},
            "negotiation": {"global_rate": 0.5, "global_trials": 100, "buckets": {}},
            "persuasion": {"global_rate": 0.5, "global_trials": 100, "buckets": {}},
        },
    }


class HostileEvidenceCore(TreatmentOffEconomicCore):
    """If any old multiplier remains wired in, these values force it to cross."""

    @staticmethod
    def _hostile() -> dict[str, float]:
        return {
            "E_concessionary": 1e300,
            "E_commitment_sensitive": 1e300,
            "E_receiver_obedient": 1e300,
            "E_sample": 1e300,
        }

    def _bargaining_evidence(self, state, beliefs):
        return self._hostile()

    def _negotiation_evidence(self, state, beliefs):
        return self._hostile()

    def _persuasion_evidence(self, state, beliefs):
        return self._hostile()


class R1TreatmentOffBaselineTests(unittest.TestCase):
    def test_bound_commit_is_wave_2_revision(self) -> None:
        self.assertEqual(BOUND_COMMIT, "895ffee341cd4893373e32d5f8c1a5375549e0e6")

    def test_four_off_wrappers_have_action_and_metadata_parity_everywhere(self) -> None:
        self.assertEqual(tuple(TREATMENT_OFF_WRAPPERS), FACTORIAL_SLOTS)
        with patch.dict(
            os.environ,
            {"GLEE_RESPONSE_MODEL": "/ambient/must/not/load", "GLEE_SUPPORT_INDEX": "/ambient/must/not/load"},
        ):
            for state in _all_family_role_action_states():
                state_before = _canonical(state)
                actions = [
                    wrapper(seed=MASTER_SEED).decide(state)
                    for wrapper in TREATMENT_OFF_WRAPPERS.values()
                ]
                self.assertEqual(len({_canonical(action) for action in actions}), 1, state.scenario_id)
                self.assertEqual(_canonical(state), state_before, state.scenario_id)
                action = actions[0]
                self.assertEqual(action.structured["strategic_mode"], "SAFE")
                self.assertEqual(action.structured["submode"], "treatment_off_economic_core")
                self.assertEqual(action.structured["evidence"], {})
                self.assertEqual(action.structured["strategic_control"]["mode"], "SAFE")
                self.assertNotIn("message_experiment", action.structured)
                self.assertNotIn('"E_', _canonical(action).decode("ascii"))

    def test_hostile_heuristic_evidence_cannot_change_any_action_byte(self) -> None:
        for state in _all_family_role_action_states():
            baseline = TreatmentOffEconomicCore(seed=MASTER_SEED).decide(state)
            hostile = HostileEvidenceCore(seed=MASTER_SEED)
            hostile.exploit_evidence_threshold = -1e300
            hostile.explore_evidence_threshold = -1e300
            observed = hostile.decide(state)
            self.assertEqual(_canonical(observed), _canonical(baseline), state.scenario_id)

    def test_language_flag_cannot_directly_change_numeric_action(self) -> None:
        for state in _all_family_role_action_states():
            off = Factorial01Wrapper(seed=MASTER_SEED, use_language=False).decide(state)
            on = Factorial01Wrapper(seed=MASTER_SEED, use_language=True).decide(state)
            self.assertEqual(on.numeric_action, off.numeric_action, state.scenario_id)
            self.assertEqual(on.accept_reject, off.accept_reject, state.scenario_id)
            self.assertEqual(on.buy_no_buy, off.buy_no_buy, state.scenario_id)
            self.assertEqual(on.structured.get("counter_price"), off.structured.get("counter_price"), state.scenario_id)
            self.assertEqual(_canonical(on), _canonical(off), state.scenario_id)

    def test_eprocess_flag_cannot_directly_change_message_rendering(self) -> None:
        for state in _all_family_role_action_states():
            off = Factorial10Wrapper(seed=MASTER_SEED, use_eprocess=False).decide(state)
            on = Factorial10Wrapper(seed=MASTER_SEED, use_eprocess=True).decide(state)
            self.assertEqual(on.message, off.message, state.scenario_id)
            self.assertEqual(on.structured.get("message"), off.structured.get("message"), state.scenario_id)
            self.assertEqual(_canonical(on), _canonical(off), state.scenario_id)

    def test_only_exact_hash_locked_response_residuals_can_load(self) -> None:
        state = _state("bargaining", "player_1", "offer")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            raw = json.dumps(_response_payload(state), sort_keys=True).encode("utf-8")
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()

            kwargs = {"response_model_path": path, "response_model_sha256": digest}
            actions = [
                wrapper(seed=MASTER_SEED, **kwargs).decide(state)
                for wrapper in TREATMENT_OFF_WRAPPERS.values()
            ]
            self.assertEqual(len({_canonical(action) for action in actions}), 1)
            self.assertIn("empirical_response_model", actions[0].structured)

            with self.assertRaisesRegex(ValueError, "requires an expected sha256"):
                TreatmentOffEconomicCore(response_model_path=path)
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                TreatmentOffEconomicCore(response_model_path=path, response_model_sha256="0" * 64)

    def test_dynamic_offline_loader_uses_the_same_core(self) -> None:
        spec = "research.CANDIDATES.r1_treatment_off_baseline:Factorial00Wrapper"
        for state in _all_family_role_action_states():
            expected = TreatmentOffEconomicCore(seed=MASTER_SEED).decide(state)
            loaded = load_agent(spec, seed=MASTER_SEED).decide(state)
            self.assertEqual(_canonical(loaded), _canonical(expected), state.scenario_id)

    def test_production_adapter_consumes_core_output_without_strategy_fallback(self) -> None:
        forced_rejection = live_fixtures.negotiation_decision(
            history=[],
            last_offer={
                "price": 13000,
                "message": "Outside your value.",
                "from_player": "player_1",
                "round": 3,
            },
        )
        rejection_seen = False
        for game in [*live_fixtures.sample_games(), forced_rejection]:
            state = to_game_state(game)
            expected_action = TreatmentOffEconomicCore(seed=MASTER_SEED).decide(state)
            expected_payload = to_live_action(game, expected_action)
            strategy = LiveStrategy(TreatmentOffEconomicCore(seed=MASTER_SEED), observation_log=None)

            observed_payload = strategy(game)

            self.assertEqual(observed_payload, expected_payload, (game["game_family"], game["valid_actions"]["type"]))
            summary = strategy.summary()
            self.assertEqual(summary["fallbacks"], 0)
            self.assertEqual(summary["counters"].get("ok"), 1)
            if game["game_family"] == "negotiation" and expected_action.accept_reject == "RejectOffer":
                rejection_seen = True
                self.assertIn("counter_price", expected_action.structured)
                self.assertIn("product_price", observed_payload)
                self.assertEqual(
                    observed_payload["product_price"],
                    round(expected_action.structured["counter_price"] * negotiation_scale(game), 2),
                )
        self.assertTrue(rejection_seen, "the production parity matrix must exercise an agent-priced rejection")


if __name__ == "__main__":
    unittest.main()
