from __future__ import annotations

import hashlib
import itertools
import json
import math
import tempfile
import unittest
from pathlib import Path

from glee_eval.data.schemas import GameState, Scenario, to_jsonable
from glee_eval.experiments.factorial import run_factorial
from research.CANDIDATES.wave3_factorial_agents import (
    EPROCESS_THRESHOLD,
    FACTORIAL_AGENTS,
    EProcessController,
    Factorial00Agent,
    Factorial01Agent,
    Factorial10Agent,
    Factorial11Agent,
)


SEED = 20260830


def _state(
    family: str,
    role: str,
    kind: str,
    *,
    round_number: int = 3,
    transcript: list[dict] | None = None,
    text: bool = False,
    quality: str = "high-quality",
    game_id: str | None = None,
) -> GameState:
    if family == "bargaining":
        public = {
            "money_to_divide": 100.0,
            "delta_1": 0.95,
            "delta_2": 0.9,
            "complete_information": True,
            "messages_allowed": True,
            "max_rounds": 8,
        }
        private = {"delta_1": 0.95, "delta_2": 0.9}
        if transcript is None and kind == "decision":
            other = "player_2" if role == "player_1" else "player_1"
            transcript = [
                {
                    "round": 2,
                    "role": other,
                    "action_type": "offer",
                    "numeric_action": 55.0,
                    "self_gain": 55.0,
                    "other_gain": 45.0,
                    "structured": {"self_gain": 55.0, "other_gain": 45.0},
                }
            ]
    elif family == "negotiation":
        public = {
            "product_price_order": 1000.0,
            "seller_value": 0.8,
            "buyer_value": 1.2,
            "complete_information": True,
            "messages_allowed": True,
            "max_rounds": 8,
        }
        private = {"seller_value": 0.8, "buyer_value": 1.2}
        if transcript is None and kind == "decision":
            other = "buyer" if role == "seller" else "seller"
            transcript = [
                {
                    "round": 2,
                    "role": other,
                    "action_type": "offer",
                    "numeric_action": 1000.0,
                    "structured": {"product_price": 1000.0},
                }
            ]
    else:
        public = {
            "product_price": 100.0,
            "p": 0.5,
            "v": 2.0,
            "c": 0.0,
            "total_rounds": 20,
            "seller_message_type": "text" if text else "binary",
            "is_seller_know_cv": True,
            "is_myopic": False,
        }
        private = {}
        if transcript is None and role == "buyer":
            transcript = [
                {
                    "round": round_number,
                    "role": "seller",
                    "action_type": "recommendation",
                    "buy_no_buy": "yes",
                    "structured": {"decision": "yes", "message": "I recommend buying."},
                }
            ]
    return GameState(
        scenario_id=f"wave3-{family}-{role}-{kind}",
        game_id=game_id or f"wave3-{family}-{role}-{kind}",
        game_family=family,
        role=role,
        round=round_number,
        horizon=20 if family == "persuasion" else 8,
        public_parameters=public,
        private_parameters=private,
        visible_transcript=list(transcript or []),
        valid_action_schema={"kind": kind},
        metadata={"quality": quality} if family == "persuasion" and role == "seller" else {},
    )


def _cells() -> list[GameState]:
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
        _state("persuasion", "seller", "recommendation", text=True),
        _state("persuasion", "buyer", "buy_decision", text=True),
    ]


def _model_payload() -> dict:
    bucket = lambda probability: {
        "probability": probability,
        "trials": 1000,
        "uncertainty": 0.01,
        "support_quality": 1.0,
    }
    return {
        "version": 1,
        "min_support": 30,
        "families": {
            "bargaining": {"global_rate": 0.5, "global_trials": 1000, "buckets": {}},
            "negotiation": {"global_rate": 0.5, "global_trials": 1000, "buckets": {}},
            "persuasion": {
                "global_rate": 0.5,
                "global_trials": 1000,
                "buckets": {"rec=yes": bucket(0.5), "rec=no": bucket(0.5)},
            },
        },
    }


class _ReferenceArtifact:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "model.json"
        raw = json.dumps(_model_payload(), sort_keys=True).encode("utf-8")
        self.path.write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        return {"response_model_path": self.path, "response_model_sha256": self.sha}

    def __exit__(self, exc_type, exc, tb):
        self.temp.cleanup()


def _history(rounds: int, *, game_id: str = "obedience-game") -> GameState:
    transcript: list[dict] = []
    for index in range(1, rounds + 1):
        transcript.extend(
            [
                {
                    "round": index,
                    "role": "nature",
                    "action_type": "nature_quality",
                    "quality": "low-quality",
                },
                {
                    "round": index,
                    "role": "seller",
                    "action_type": "recommendation",
                    "buy_no_buy": "yes",
                    "structured": {
                        "decision": "yes",
                        "message": "I recommend buying this product.",
                    },
                },
                {
                    "round": index,
                    "role": "buyer",
                    "action_type": "buy_decision",
                    "buy_no_buy": "yes",
                    "structured": {"decision": "yes"},
                },
            ]
        )
    return _state(
        "persuasion",
        "seller",
        "recommendation",
        round_number=rounds + 1,
        transcript=transcript,
        text=True,
        quality="low-quality",
        game_id=game_id,
    )


class Wave3FactorialAgentTests(unittest.TestCase):
    def test_four_forced_entrypoints_reject_flag_overrides(self) -> None:
        for cls in FACTORIAL_AGENTS.values():
            with self.assertRaises(TypeError):
                cls(use_eprocess=False)
            with self.assertRaises(TypeError):
                cls(use_language=False)

    def test_all_four_are_callable_in_every_family_role_action_cell(self) -> None:
        for state in _cells():
            for cls in FACTORIAL_AGENTS.values():
                action = cls(seed=SEED).decide(state)
                self.assertTrue(action.is_legal, (cls.__name__, state.scenario_id))
                self.assertNotIn('"E_', json.dumps(to_jsonable(action), sort_keys=True))

    def test_language_never_changes_numeric_or_economic_decision(self) -> None:
        for state in _cells():
            off = Factorial00Agent(seed=SEED).decide(state)
            on = Factorial01Agent(seed=SEED).decide(state)
            self.assertEqual(off.numeric_action, on.numeric_action, state.scenario_id)
            self.assertEqual(off.accept_reject, on.accept_reject, state.scenario_id)
            self.assertEqual(off.buy_no_buy, on.buy_no_buy, state.scenario_id)

    def test_eligible_language_differs_and_unsupported_cells_are_exactly_inert(self) -> None:
        eligible = _state("persuasion", "seller", "recommendation", text=True)
        off = Factorial00Agent(seed=SEED).decide(eligible)
        on = Factorial01Agent(seed=SEED).decide(eligible)
        self.assertNotEqual(off.message, on.message)
        self.assertTrue(on.structured["language_treatment"]["eligible"])

        unsupported = [
            state
            for state in _cells()
            if not (state.game_family == "persuasion" and state.role == "seller")
        ]
        unsupported.append(_state("persuasion", "seller", "recommendation", text=False))
        for state in unsupported:
            off = Factorial00Agent(seed=SEED).decide(state)
            on = Factorial01Agent(seed=SEED).decide(state)
            self.assertEqual(to_jsonable(off), to_jsonable(on), state.scenario_id)

    def test_eprocess_does_not_change_rendering_before_an_economic_change(self) -> None:
        for state in _cells():
            off = Factorial00Agent(seed=SEED).decide(state)
            on = Factorial10Agent(seed=SEED).decide(state)
            self.assertEqual(off.message, on.message, state.scenario_id)
            self.assertEqual(off.structured.get("message"), on.structured.get("message"), state.scenario_id)

    def test_eprocess_accumulates_real_idempotent_state_and_resets(self) -> None:
        with _ReferenceArtifact() as artifact:
            treated = Factorial10Agent(seed=SEED, **artifact)
            first = treated.decide(_history(1))
            report = first.structured["eprocess_treatment"]
            self.assertEqual(report["updates"], 1)
            self.assertEqual(report["evalue"], 1.5)
            repeat = treated.decide(_history(1))
            self.assertEqual(repeat.structured["eprocess_treatment"]["updates"], 1)
            reset = treated.decide(_history(0, game_id="new-game"))
            self.assertEqual(reset.structured["eprocess_treatment"]["updates"], 0)
            self.assertEqual(reset.structured["eprocess_treatment"]["evalue"], 1.0)

            control = Factorial00Agent(seed=SEED, **artifact).decide(_history(1))
            self.assertNotIn("eprocess_treatment", control.structured)

    def test_11_contains_both_treatments_without_rng_or_state_aliasing(self) -> None:
        with _ReferenceArtifact() as artifact:
            state = _history(1)
            both_agent = Factorial11Agent(seed=SEED, **artifact)
            both = both_agent.decide(state)
            language = Factorial01Agent(seed=SEED, **artifact).decide(state)
            evidence = Factorial10Agent(seed=SEED, **artifact).decide(state)
            self.assertIn("eprocess_treatment", both.structured)
            self.assertIn("language_treatment", both.structured)
            self.assertEqual(both.message, language.message)
            self.assertEqual(
                both.structured["eprocess_treatment"]["evalue"],
                evidence.structured["eprocess_treatment"]["evalue"],
            )
            audit = both_agent.factorial_randomness_audit()
            self.assertEqual(
                set(audit["claims"]),
                {"economic_policy", "eprocess_treatment", "language_treatment"},
            )

    def test_threshold_crossing_changes_only_supported_economic_scope(self) -> None:
        with _ReferenceArtifact() as artifact:
            treated = Factorial10Agent(seed=SEED, **artifact)
            action = treated.decide(_history(8))
            report = action.structured["eprocess_treatment"]
            self.assertGreaterEqual(report["evalue"], EPROCESS_THRESHOLD)
            self.assertTrue(report["crossed"])
            self.assertEqual(report["economic_override"], "recommend_yes_after_crossing")
            self.assertEqual(action.buy_no_buy, "yes")

    def test_exact_null_enumeration_respects_ville_bound(self) -> None:
        # Under p0=.5 and q=.75, this exhaustively checks the implementation's
        # factors through horizon 12. It is a simulation/check, not the proof.
        horizon = 12
        crossing_probability = 0.0
        for outcomes in itertools.product((0, 1), repeat=horizon):
            value = 1.0
            crossed = False
            for observed in outcomes:
                value *= 1.5 if observed else 0.5
                crossed |= value >= EPROCESS_THRESHOLD
            if crossed:
                crossing_probability += 0.5**horizon
        self.assertLessEqual(crossing_probability, 1.0 / EPROCESS_THRESHOLD)
        self.assertTrue(math.isclose(0.5 * 1.5 + 0.5 * 0.5, 1.0))
        for p0 in (0.1, 0.5, 0.9):
            q = p0 + 0.5 * (1.0 - p0)
            for actual in (0.0, p0 / 2.0, p0):
                expectation = actual * (q / p0) + (1.0 - actual) * (
                    (1.0 - q) / (1.0 - p0)
                )
                self.assertLessEqual(expectation, 1.0 + 1e-15)

    def test_eprocess_never_reads_current_or_future_round_outcomes(self) -> None:
        with _ReferenceArtifact() as artifact:
            base = _history(1)
            transcript = list(base.visible_transcript)
            for index in (2, 3):
                transcript.extend(
                    [
                        {
                            "round": index,
                            "role": "nature",
                            "action_type": "nature_quality",
                            "quality": "low-quality",
                        },
                        {
                            "round": index,
                            "role": "seller",
                            "action_type": "recommendation",
                            "buy_no_buy": "yes",
                            "structured": {"decision": "yes"},
                        },
                        {
                            "round": index,
                            "role": "buyer",
                            "action_type": "buy_decision",
                            "buy_no_buy": "yes",
                            "structured": {"decision": "yes"},
                        },
                    ]
                )
            adversarial = GameState(
                **{
                    **base.__dict__,
                    "round": 2,
                    "visible_transcript": transcript,
                }
            )
            action = Factorial10Agent(seed=SEED, **artifact).decide(adversarial)
            report = action.structured["eprocess_treatment"]
            self.assertEqual(report["updates"], 1)
            self.assertEqual(report["trace"][0]["round"], 1)

    def test_controller_explicitly_rejects_unsupported_acting_scopes(self) -> None:
        treated = Factorial10Agent(seed=SEED)
        for state in (
            _state("bargaining", "player_1", "offer"),
            _state("negotiation", "seller", "offer"),
            _state("persuasion", "buyer", "buy_decision", text=True),
        ):
            action = treated.decide(state)
            report = action.structured["eprocess_treatment"]
            self.assertTrue(report["status"].startswith("unsupported:"))
            self.assertEqual(report["evalue"], 1.0)

    def test_four_real_entrypoints_run_under_repaired_factorial_capabilities(self) -> None:
        def scenario(family: str, seed: int, role: str) -> Scenario:
            self.assertEqual(family, "persuasion")
            other = "buyer" if role == "seller" else "seller"
            return Scenario(
                scenario_id=f"wave3-factorial-{seed}-{role}",
                game_family="persuasion",
                config_id=f"wave3-text-{seed}",
                public_parameters={
                    "p": 0.5,
                    "v": 2.0,
                    "c": 0.0,
                    "product_price": 100.0,
                    "total_rounds": 4,
                    "is_seller_know_cv": True,
                    "seller_message_type": "text",
                    "is_myopic": False,
                },
                candidate_role=role,
                opponent_role=other,
                opponent_spec={
                    "archetype": "rational",
                    "parameters": {
                        "honesty": 0.75,
                        "yes_on_low_rate": 0.25,
                        "trust_prior": 0.75,
                    },
                    "seed": seed + 1,
                },
                seed=seed,
            )

        with _ReferenceArtifact() as artifact:
            factories = {
                arm: (lambda context, cls=cls: cls(arm_context=context, **artifact))
                for arm, cls in FACTORIAL_AGENTS.items()
            }
            rows = run_factorial(
                factories,
                families=["persuasion"],
                games=2,
                seed=SEED,
                scenario_factory=scenario,
                require_inert_parity=False,
                require_active_isolation_canary=True,
            )
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(
                row.arm("e0_l0").non_language_record_hash,
                row.arm("e0_l1").non_language_record_hash,
            )
            for arm in row.arms:
                expected = {"economic_policy"}
                if arm.use_eprocess:
                    expected.add("eprocess_treatment")
                if arm.use_language:
                    expected.add("language_treatment")
                self.assertEqual(set(arm.randomness_audit["claims"]), expected)


if __name__ == "__main__":
    unittest.main()
