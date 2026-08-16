from __future__ import annotations

import unittest
from dataclasses import replace

from glee_eval.data.schemas import GameState, OpponentSpec, to_jsonable
from glee_eval.opponents.policies import PolicyFactory


def _state(family: str, text: str) -> GameState:
    if family == "bargaining":
        public = {"money_to_divide": 100.0}
        private = {}
        role = "player_2"
        transcript = [{
            "round": 1, "role": "player_1", "action_type": "offer",
            "numeric_action": 60.0, "self_gain": 60.0, "other_gain": 40.0,
            "structured": {"self_gain": 60.0, "other_gain": 40.0},
            "free_text_message": text,
        }]
    elif family == "negotiation":
        public = {"product_price_order": 10_000.0}
        private = {"seller_value": 0.7, "buyer_value": 1.1}
        role = "buyer"
        transcript = [{
            "round": 1, "role": "seller", "action_type": "offer",
            "numeric_action": 9_000.0,
            "structured": {"product_price": 9_000.0},
            "free_text_message": text,
        }]
    else:
        public = {"seller_message_type": "text"}
        private = {}
        role = "buyer"
        # Hold the structured stance fixed: R3 may alter words, not the economic
        # recommendation that the production opponent actually consumes.
        transcript = [{
            "round": 1, "role": "seller", "action_type": "message",
            "buy_no_buy": "yes", "structured": {"decision": "yes"},
            "free_text_message": text,
        }]
    return GameState(
        scenario_id="r3", game_id=f"r3-{family}", game_family=family,
        role=role, round=1, horizon=6, public_parameters=public,
        private_parameters=private, visible_transcript=transcript,
        valid_action_schema={"kind": "decision", "seller_message_type": "text"},
    )


def _spec(family: str) -> OpponentSpec:
    parameters = {
        "bargaining": {"target_share": 0.58, "accept_threshold": 0.39},
        "negotiation": {"accept_margin": 0.02},
        "persuasion": {"trust_prior": 0.63, "buy_after_no_rate": 0.022},
    }[family]
    return OpponentSpec(
        archetype="rational", game_family=family, parameters=parameters, seed=104729,
    )


class R3LanguageCausalFeasibilityTests(unittest.TestCase):
    def test_text_only_perturbation_is_inert_for_every_offline_opponent_family(self) -> None:
        texts = (
            "I think this is a fair proposal.",
            "Reject this terrible proposal immediately.",
        )
        for family in ("bargaining", "negotiation", "persuasion"):
            with self.subTest(family=family):
                baseline = _state(family, texts[0])
                treatment = replace(
                    baseline,
                    visible_transcript=[{**baseline.visible_transcript[0], "free_text_message": texts[1]}],
                )
                self.assertNotEqual(
                    baseline.visible_transcript[0]["free_text_message"],
                    treatment.visible_transcript[0]["free_text_message"],
                )
                baseline_without_text = {
                    **baseline.visible_transcript[0], "free_text_message": None,
                }
                treatment_without_text = {
                    **treatment.visible_transcript[0], "free_text_message": None,
                }
                self.assertEqual(baseline_without_text, treatment_without_text)

                spec = _spec(family)
                left = PolicyFactory.create(family, spec).decide(baseline)
                right = PolicyFactory.create(family, spec).decide(treatment)
                self.assertEqual(to_jsonable(left), to_jsonable(right))


if __name__ == "__main__":
    unittest.main()
