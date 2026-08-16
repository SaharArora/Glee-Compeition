from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from glee_eval.adapters.candidate_agent import CandidateAgent, RandomLegalAgent
from glee_eval.data.schemas import AgentAction, GameState, Scenario, compact_id
from glee_eval.experiments.ab import run_paired_ab


class _WordingOnlyWrapper(CandidateAgent):
    """Deliberately bad wrapper used to test evaluator isolation.

    The treatment draw represents wording selection. Sharing that draw with the
    economic policy contaminates the recommendation even though the intended
    treatment surface is text only. A factorial evaluator must reject this arm,
    not report its payoff change as a language effect.
    """

    agent_id = "r4-wording-wrapper"

    def __init__(self, *, language_on: bool) -> None:
        self.language_on = language_on
        self.rng = random.Random(7)

    def decide(self, state: GameState) -> AgentAction:
        if self.language_on:
            self.rng.random()
        decision = "yes" if self.rng.random() < 0.5 else "no"
        message = "A longer grounded explanation." if self.language_on else "Buy."
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, decision, self.language_on),
            actor_role=state.role,
            round=state.round,
            raw_text=message,
            action_type="message",
            message=message,
            buy_no_buy=decision,
            structured={"decision": decision},
        )


def _persuasion_seller_scenario() -> Scenario:
    return Scenario(
        scenario_id="r4-treatment-contamination",
        game_family="persuasion",
        config_id="r4-config",
        public_parameters={
            "total_rounds": 8,
            "p": 1.0,
            "v": 2.0,
            "c": 0.0,
            "product_price": 100,
            "seller_message_type": "text",
            "is_seller_know_cv": True,
            "is_myopic": False,
        },
        candidate_role="seller",
        opponent_role="buyer",
        opponent_spec={
            "archetype": "rational",
            "parameters": {"trust_prior": 1.0, "buy_after_no_rate": 0.0},
            "seed": 9,
        },
        seed=11,
    )


class R4PairingKillCheckTests(unittest.TestCase):
    def test_identical_seeded_agents_have_zero_paired_difference(self) -> None:
        observations = run_paired_ab(
            lambda: RandomLegalAgent(seed=7),
            lambda: RandomLegalAgent(seed=7),
            families=["bargaining", "negotiation", "persuasion"],
            games=60,
            seed=20260829,
        )
        self.assertTrue(all(row.difference == 0.0 for row in observations))

    def test_two_arm_runner_does_not_reject_rng_treatment_contamination(self) -> None:
        scenario = _persuasion_seller_scenario()
        with patch("glee_eval.experiments.ab.sample_scenario", return_value=scenario):
            row = run_paired_ab(
                lambda: _WordingOnlyWrapper(language_on=False),
                lambda: _WordingOnlyWrapper(language_on=True),
                families=["persuasion"],
                games=1,
                seed=20260829,
            )[0]

        # This nonzero result is deliberately invalid: the evaluator did not
        # detect that a wording-only treatment changed the numeric stance by
        # consuming the economic RNG stream.
        self.assertEqual(row.difference, 0.125)


if __name__ == "__main__":
    unittest.main()
