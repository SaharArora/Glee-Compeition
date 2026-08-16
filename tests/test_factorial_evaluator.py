from __future__ import annotations

import random
import unittest
from collections import OrderedDict

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import AgentAction, GameState, Scenario, compact_id, to_jsonable
from glee_eval.experiments.factorial import (
    ARM_FLAGS,
    FACTORIAL_ARMS,
    ArmContext,
    FactorialIntegrityError,
    integrity_certificate,
    run_factorial,
)


def _action(state: GameState, decision: str, numeric: float | None = None) -> AgentAction:
    if state.game_family == "bargaining":
        if state.valid_action_schema.get("kind") == "offer":
            money = float(state.public_parameters["money_to_divide"])
            numeric = 60.0 if numeric is None else numeric
            return AgentAction(
                action_id=compact_id(state.game_id, state.round, state.role, numeric),
                actor_role=state.role,
                round=state.round,
                raw_text=str(numeric),
                action_type="offer",
                numeric_action=numeric,
                structured={"self_gain": numeric, "other_gain": money - numeric},
            )
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, state.role, "accept"),
            actor_role=state.role,
            round=state.round,
            raw_text="accept",
            action_type="decision",
            accept_reject="accept",
            structured={"decision": "accept"},
        )
    if state.game_family == "negotiation":
        if state.valid_action_schema.get("kind") == "offer":
            numeric = 90.0 if numeric is None else numeric
            return AgentAction(
                action_id=compact_id(state.game_id, state.round, state.role, numeric),
                actor_role=state.role,
                round=state.round,
                raw_text=str(numeric),
                action_type="offer",
                numeric_action=numeric,
                structured={"product_price": numeric},
            )
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, state.role, "AcceptOffer"),
            actor_role=state.role,
            round=state.round,
            raw_text="AcceptOffer",
            action_type="decision",
            accept_reject="AcceptOffer",
            structured={"decision": "AcceptOffer"},
        )
    answer = decision
    return AgentAction(
        action_id=compact_id(state.game_id, state.round, state.role, answer),
        actor_role=state.role,
        round=state.round,
        raw_text=answer,
        action_type="recommendation" if state.role == "seller" else "buy_decision",
        buy_no_buy=answer,
        structured={"decision": answer},
    )


class _NoopAgent(CandidateAgent):
    agent_id = "factorial-shared-core"

    def __init__(self, context: ArmContext, *, extra_language_draws: int = 0, contaminated: bool = False) -> None:
        self.context = context
        self.economic_rng = random.Random(context.economic_seed)
        self.language_rng = random.Random(context.language_seed)
        self.extra_language_draws = extra_language_draws
        self.contaminated = contaminated

    def decide(self, state: GameState) -> AgentAction:
        for _ in range(self.extra_language_draws if self.context.use_language else 0):
            if self.contaminated:
                self.economic_rng.random()
            else:
                self.language_rng.random()
        economic_draw = self.economic_rng.random()
        if state.game_family == "bargaining" and state.valid_action_schema.get("kind") == "offer":
            return _action(state, "yes", 55.0 if economic_draw < 0.5 else 60.0)
        if state.game_family == "negotiation" and state.valid_action_schema.get("kind") == "offer":
            return _action(state, "yes", 85.0 if economic_draw < 0.5 else 90.0)
        return _action(state, "yes" if economic_draw < 0.5 else "no")


def _factories(*, extra_language_draws: int = 0, contaminated: bool = False, reverse: bool = False):
    names = list(reversed(FACTORIAL_ARMS)) if reverse else list(FACTORIAL_ARMS)
    return OrderedDict(
        (
            name,
            lambda context, draws=extra_language_draws, bad=contaminated: _NoopAgent(
                context, extra_language_draws=draws, contaminated=bad
            ),
        )
        for name in names
    )


def _scenario(family: str, seed: int, role: str) -> Scenario:
    configs = {
        "bargaining": {
            "money_to_divide": 100,
            "max_rounds": 4,
            "complete_information": True,
            "messages_allowed": True,
            "delta_1": 0.9,
            "delta_2": 0.95,
        },
        "negotiation": {
            "seller_value": 70.0,
            "buyer_value": 110.0,
            "product_price_order": 100.0,
            "max_rounds": 4,
            "complete_information": True,
            "messages_allowed": True,
        },
        "persuasion": {
            "p": 0.5,
            "v": 2.0,
            "c": 0.0,
            "product_price": 100,
            "total_rounds": 8,
            "is_seller_know_cv": True,
            "is_buyer_know_p": True,
            "seller_message_type": "binary",
            "is_myopic": False,
        },
    }
    roles = {
        "bargaining": ("player_1", "player_2"),
        "negotiation": ("seller", "buyer"),
        "persuasion": ("seller", "buyer"),
    }[family]
    opponent = roles[1] if role == roles[0] else roles[0]
    params = {
        "bargaining": {"target_share": 0.55, "accept_threshold": 0.4, "action_noise": 0.02},
        "negotiation": {"aspiration_price": 0.9, "accept_margin": 0.02, "action_noise": 0.02},
        "persuasion": {"honesty": 0.75, "yes_on_low_rate": 0.25, "trust_prior": 0.75},
    }[family]
    return Scenario(
        scenario_id=f"factorial-{family}-{seed}-{role}",
        game_family=family,
        config_id=f"config-{family}-{seed}",
        public_parameters=configs[family],
        candidate_role=role,
        opponent_role=opponent,
        opponent_spec={"archetype": "rational", "parameters": params, "seed": seed + 17},
        seed=seed,
        metadata={"fixture": "factorial-integrity"},
    )


def _run(factories, *, require_inert_parity: bool = True):
    return run_factorial(
        factories,
        families=["bargaining", "negotiation", "persuasion"],
        games=12,
        seed=20260829,
        scenario_factory=_scenario,
        support_mask_fn=lambda scenario: {"inside_support": scenario.config_id.endswith(str(scenario.seed))},
        eligibility_fn=lambda scenario: {
            "language_eligible": scenario.game_family == "persuasion",
            "source": scenario.source,
        },
        require_inert_parity=require_inert_parity,
    )


class FactorialEvaluatorIntegrityTests(unittest.TestCase):
    def test_four_noop_wrappers_have_identical_actions_and_outcomes(self) -> None:
        rows = _run(_factories())
        for row in rows:
            self.assertEqual(len({arm.unlabeled_record_hash for arm in row.arms}), 1)
            self.assertEqual(len({arm.candidate_payoff for arm in row.arms}), 1)

    def test_treatment_random_draws_do_not_change_environment_or_opponent(self) -> None:
        baseline = _run(_factories(extra_language_draws=0))
        extra = _run(_factories(extra_language_draws=19))
        self.assertEqual(
            [[item.unlabeled_record_hash for item in row.arms] for row in baseline],
            [[item.unlabeled_record_hash for item in row.arms] for row in extra],
        )
        for left, right in zip(baseline, extra, strict=True):
            self.assertEqual(
                [(arm.environment_stream_hash, arm.opponent_stream_hash) for arm in left.arms],
                [(arm.environment_stream_hash, arm.opponent_stream_hash) for arm in right.arms],
            )

    def test_inert_language_has_exact_zero_paired_effect(self) -> None:
        rows = _run(_factories(extra_language_draws=7))
        for row in rows:
            self.assertEqual(row.contrasts()["language_main_effect"], 0.0)
            self.assertEqual(row.contrasts()["interaction"], 0.0)

    def test_scenario_roles_support_and_eligibility_are_four_way_paired(self) -> None:
        rows = _run(_factories())
        certificate = integrity_certificate(rows)
        self.assertTrue(certificate["paired_manifest_fields_identical"])
        self.assertEqual(len(certificate["roles"]), 6)
        for row in rows:
            for field in (
                "scenario_hash",
                "initial_state_hash",
                "support_mask_hash",
                "eligibility_hash",
                "environment_stream_hash",
                "opponent_stream_hash",
                "economic_stream_hash",
            ):
                self.assertEqual(len({getattr(arm, field) for arm in row.arms}), 1)

    def test_arm_mapping_order_cannot_change_results(self) -> None:
        forward = _run(_factories())
        reverse = _run(_factories(reverse=True))
        self.assertEqual(
            [[to_jsonable(arm) for arm in row.arms] for row in forward],
            [[to_jsonable(arm) for arm in row.arms] for row in reverse],
        )

    def test_removing_treatment_labels_makes_noop_records_indistinguishable(self) -> None:
        rows = _run(_factories())
        for row in rows:
            self.assertEqual(len({arm.unlabeled_record_hash for arm in row.arms}), 1)

    def test_shared_rng_contamination_is_rejected_before_scoring(self) -> None:
        with self.assertRaises(FactorialIntegrityError):
            _run(_factories(extra_language_draws=1, contaminated=True))


if __name__ == "__main__":
    unittest.main()
