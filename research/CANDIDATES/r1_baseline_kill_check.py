"""Bounded R1 counterexample for the four treatment-off wrapper mapping.

This is research evidence, not a proposed e-process or language mechanism.  It
maps each factorial slot to the currently shipped ``MyAgent`` and checks that
mapping against the smallest treatment-off economic-core projection: identical
theory and empirical-response residual code, with only the heuristic ``E_*``
mode gate disabled.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from typing import Any

from glee_eval.data.schemas import GameState, to_jsonable
from glee_eval.response_models.runtime import EmpiricalResponseModel, bargaining_keys
from my_agents.jordan_strategic import MyAgent, StrategicControl, StrategicMode


COMMIT = "bce578597dbfacf2ebca38399edb41a5dde2f936"
MASTER_SEED = 20260829
FACTORIAL_SLOTS = ("00", "10", "01", "11")


class _TreatmentOffEconomicCore(MyAgent):
    """Current economic core with the forbidden heuristic mode gate removed."""

    def _control(
        self,
        state: GameState,
        beliefs: dict[str, float],
        evidence: dict[str, float],
        family: str,
    ) -> StrategicControl:
        coverage: dict[str, Any] = {"known": False, "reason": "R1 fixture"}
        return StrategicControl(
            StrategicMode.SAFE,
            "economic_core",
            self._expected_exploitation_gain(state, family, beliefs, evidence),
            self._posterior_regret(state, beliefs, evidence),
            evidence,
            beliefs,
            "heuristic E_* mode gate disabled",
            coverage,
            self._counterfactual_uncertainty(state, beliefs, evidence, coverage),
        )


def _fixture() -> GameState:
    return GameState(
        scenario_id="r1-adversarial",
        game_id="r1-adversarial",
        game_family="bargaining",
        role="player_1",
        round=1,
        horizon=6,
        public_parameters={
            "money_to_divide": 100,
            "delta_1": 0.99,
            "delta_2": 0.80,
            "complete_information": True,
            "messages_allowed": True,
        },
        private_parameters={"delta_1": 0.99, "delta_2": 0.80},
        visible_transcript=[],
        valid_action_schema={"kind": "offer"},
        metadata={},
    )


def _response_model(state: GameState) -> EmpiricalResponseModel:
    """Small deterministic residual fixture that both sides actually consume."""

    buckets: dict[str, dict[str, float | int]] = {}
    for index in range(7):
        self_share = round(0.50 + index * 0.02, 2)
        key = bargaining_keys(state, "player_2", 1.0 - self_share)[0]
        buckets[key] = {
            "probability": 1.0 if self_share == 0.62 else 0.50,
            "trials": 100,
            "uncertainty": 0.0,
            "support_quality": 1.0,
        }
    return EmpiricalResponseModel(
        {
            "version": 1,
            "min_support": 1,
            "families": {
                "bargaining": {
                    "global_rate": 0.5,
                    "global_trials": 100,
                    "buckets": buckets,
                }
            },
        }
    )


def _agent(kind: type[MyAgent], state: GameState) -> MyAgent:
    agent = kind(seed=MASTER_SEED, response_model_path="", support_index_path="")
    agent.response_model = _response_model(state)
    agent.coverage_gate = None
    return agent


def _bytes(value: Any) -> bytes:
    return json.dumps(
        to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def run() -> dict[str, Any]:
    state = _fixture()
    state_before = _bytes(state)
    wrappers = {slot: _agent(MyAgent, state) for slot in FACTORIAL_SLOTS}
    wrapper_actions = {slot: agent.decide(state) for slot, agent in wrappers.items()}
    core = _agent(_TreatmentOffEconomicCore, state)
    core_action = core.decide(state)
    representative = wrapper_actions["00"]

    certificate = {
        "claim": "verified_counterexample",
        "commit": COMMIT,
        "seed": MASTER_SEED,
        "sample_size": 1,
        "factorial_slots": list(FACTORIAL_SLOTS),
        "fixture_sha256": hashlib.sha256(state_before).hexdigest(),
        "input_state_unchanged": state_before == _bytes(state),
        "four_wrapper_action_bytes_identical": len({_bytes(value) for value in wrapper_actions.values()}) == 1,
        "four_wrapper_instance_state_identical": len(
            {pickle.dumps(agent.__dict__, protocol=5) for agent in wrappers.values()}
        )
        == 1,
        "residual_used_by_wrapper": "empirical_response_model" in representative.structured,
        "residual_used_by_core": "empirical_response_model" in core_action.structured,
        "wrapper_mode": representative.structured["strategic_mode"],
        "core_mode": core_action.structured["strategic_mode"],
        "wrapper_numeric_action": representative.numeric_action,
        "core_numeric_action": core_action.numeric_action,
        "wrapper_action_sha256": hashlib.sha256(_bytes(representative)).hexdigest(),
        "core_action_sha256": hashlib.sha256(_bytes(core_action)).hexdigest(),
        "wrapper_equals_core": _bytes(representative) == _bytes(core_action),
    }
    if not certificate["four_wrapper_action_bytes_identical"]:
        raise AssertionError("the four current mappings unexpectedly differ from each other")
    if not certificate["four_wrapper_instance_state_identical"]:
        raise AssertionError("the four current mappings unexpectedly differ in instance state")
    if certificate["wrapper_equals_core"]:
        raise AssertionError("fixture no longer demonstrates treatment-off core divergence")
    return certificate


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
