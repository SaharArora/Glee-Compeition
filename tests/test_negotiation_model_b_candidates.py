from __future__ import annotations

import unittest
from dataclasses import replace

from glee_eval.data.schemas import GameState
from glee_eval.experiments.ab import negotiation_debias_counterpart_window, negotiation_time_concession_window, unknown_horizon_counter_preservation_window
from my_agents.jordan_strategic import MyAgent
from my_agents.negotiation_model_b_candidates import DebiasCounterpartValueModelBCandidate, GuaranteeOwnMarginModelBCandidate, TimeConcessionModelBCandidate, UnknownHorizonCounterPreservationModelBCandidate

FLAGS = ("use_time_concession", "guarantee_own_margin", "debias_counterpart_value", "use_unknown_horizon_counter_fallback", "use_unknown_horizon_counter_preservation")


def _state(role: str = "buyer", *, prior: bool = True, horizon_known: bool = False, round_: int = 4) -> GameState:
    opponent = "seller" if role == "buyer" else "buyer"
    transcript = []
    if prior:
        transcript.append({"round": 2, "role": role, "action_type": "offer", "numeric_action": 8_437.5 if role == "buyer" else 11_562.5})
    transcript.append({"round": round_, "role": opponent, "action_type": "offer", "numeric_action": 12_000.0 if role == "buyer" else 8_000.0})
    return GameState(
        scenario_id="s", game_id="g", game_family="negotiation", role=role, round=round_, horizon=10,
        public_parameters={"product_price_order": 10_000.0, "max_rounds": 10, "complete_information": False},
        private_parameters={"buyer_value" if role == "buyer" else "seller_value": 1.0},
        visible_transcript=transcript, valid_action_schema={"kind": "decision"}, metadata={"horizon_known": horizon_known},
    )


class ModelBCandidateTests(unittest.TestCase):
    def test_entry_points_enable_exactly_one_candidate_flag(self) -> None:
        cases = {TimeConcessionModelBCandidate: "use_time_concession", GuaranteeOwnMarginModelBCandidate: "guarantee_own_margin", DebiasCounterpartValueModelBCandidate: "debias_counterpart_value", UnknownHorizonCounterPreservationModelBCandidate: "use_unknown_horizon_counter_preservation"}
        for cls, enabled in cases.items():
            agent = cls(guarantee_own_margin=True, use_unknown_horizon_counter_fallback=True)
            self.assertEqual([flag for flag in FLAGS if getattr(agent, flag)], [enabled])

    def test_preservation_repeats_exact_raw_offer_for_both_roles(self) -> None:
        for role, raw, normalized in (("buyer", 8_437.5, 0.84375), ("seller", 11_562.5, 1.15625)):
            state = _state(role)
            baseline = MyAgent().decide(state)
            candidate = UnknownHorizonCounterPreservationModelBCandidate().decide(state)
            self.assertEqual(candidate.accept_reject, "RejectOffer")
            self.assertNotIn("counter_price", baseline.structured)
            self.assertEqual(candidate.structured["counter_price"], raw)
            self.assertEqual(candidate.structured["counter_normalized_price"], normalized)

    def test_preservation_off_branches_and_condition_four_recording(self) -> None:
        eligible = _state()
        self.assertTrue(unknown_horizon_counter_preservation_window(eligible, MyAgent()))
        for state in (replace(eligible, metadata={"horizon_known": True}), _state(prior=False)):
            self.assertFalse(unknown_horizon_counter_preservation_window(state, MyAgent()))
            self.assertNotIn("counter_price", UnknownHorizonCounterPreservationModelBCandidate().decide(state).structured)
        accepting = replace(eligible, visible_transcript=[*eligible.visible_transcript[:-1], {"round": 4, "role": "seller", "action_type": "offer", "numeric_action": 9_000.0}])
        self.assertNotEqual(MyAgent().decide(accepting).accept_reject, "RejectOffer")
        self.assertFalse(unknown_horizon_counter_preservation_window(accepting, MyAgent()))

    def test_time_and_debias_predicate_boundaries(self) -> None:
        offer = replace(_state(), valid_action_schema={"kind": "offer"})
        self.assertTrue(negotiation_time_concession_window(offer, MyAgent()))
        self.assertFalse(negotiation_time_concession_window(replace(offer, round=1), MyAgent()))
        self.assertFalse(negotiation_time_concession_window(replace(offer, horizon=1), MyAgent()))
        self.assertTrue(negotiation_debias_counterpart_window(_state(), MyAgent()))
        known = replace(_state(), public_parameters={**_state().public_parameters, "complete_information": True, "seller_value": 1.0, "buyer_value": 1.0})
        self.assertFalse(negotiation_debias_counterpart_window(known, MyAgent()))


if __name__ == "__main__":
    unittest.main()
