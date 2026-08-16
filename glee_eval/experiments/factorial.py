"""Four-arm paired evaluator with explicit treatment-isolation provenance.

This module is research infrastructure.  It does not define either treatment and
does not authorize a payoff experiment.  Its job is to make the pairing contract
executable before an arm is allowed to enter the frozen 2x2 study.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import EpisodeResult, Scenario, to_jsonable
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.opponent_fit import OpponentPopulation
from glee_eval.population.sampler import sample_scenario
from glee_eval.tournament.runner import run_episode


FACTORIAL_ARMS = ("e0_l0", "e0_l1", "e1_l0", "e1_l1")
ARM_FLAGS = {
    "e0_l0": (False, False),
    "e0_l1": (False, True),
    "e1_l0": (True, False),
    "e1_l1": (True, True),
}
FAMILY_ROLES = {
    "bargaining": ("player_1", "player_2"),
    "negotiation": ("seller", "buyer"),
    "persuasion": ("seller", "buyer"),
}


class FactorialIntegrityError(RuntimeError):
    """Raised before scoring when the pairing/isolation contract is violated."""


@dataclass(frozen=True)
class ArmContext:
    arm: str
    use_eprocess: bool
    use_language: bool
    scenario_id: str
    economic_seed: int
    eprocess_seed: int
    language_seed: int
    environment_seed: int
    opponent_seed: int

    def seed_manifest(self) -> dict[str, int]:
        return {
            "economic": self.economic_seed,
            "eprocess": self.eprocess_seed,
            "language": self.language_seed,
            "environment": self.environment_seed,
            "opponent": self.opponent_seed,
        }


@dataclass(frozen=True)
class ArmResult:
    arm: str
    use_eprocess: bool
    use_language: bool
    candidate_payoff: float
    opponent_payoff: float
    scenario_hash: str
    initial_state_hash: str
    support_mask_hash: str
    eligibility_hash: str
    environment_stream_hash: str
    opponent_stream_hash: str
    economic_stream_hash: str
    episode_hash: str
    unlabeled_record_hash: str
    episode: EpisodeResult


@dataclass(frozen=True)
class FactorialRow:
    key: str
    family: str
    candidate_role: str
    scenario_hash: str
    initial_state_hash: str
    support_mask: Any
    support_mask_hash: str
    eligibility: Any
    eligibility_hash: str
    arms: tuple[ArmResult, ...]

    def arm(self, name: str) -> ArmResult:
        return next(item for item in self.arms if item.arm == name)

    def contrasts(self) -> dict[str, float]:
        y00 = self.arm("e0_l0").candidate_payoff
        y01 = self.arm("e0_l1").candidate_payoff
        y10 = self.arm("e1_l0").candidate_payoff
        y11 = self.arm("e1_l1").candidate_payoff
        return {
            "eprocess_main_effect": 0.5 * ((y10 - y00) + (y11 - y01)),
            "language_main_effect": 0.5 * ((y01 - y00) + (y11 - y10)),
            "interaction": y11 - y10 - y01 + y00,
        }


AgentFactory = Callable[[ArmContext], CandidateAgent]
ScenarioFactory = Callable[[str, int, str], Scenario]
MaskFactory = Callable[[Scenario], Any]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _named_seed(master_seed: int, scenario_id: str, stream: str) -> int:
    payload = f"glee.factorial.v1|{master_seed}|{scenario_id}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


def _scenario_seed(master_seed: int, family: str, family_index: int) -> int:
    payload = f"glee.factorial.v1|{master_seed}|scenario|{family}|{family_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


def _initial_state_manifest(scenario: Scenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "family": scenario.game_family,
        "config_id": scenario.config_id,
        "public_parameters": scenario.public_parameters,
        "candidate_role": scenario.candidate_role,
        "opponent_role": scenario.opponent_role,
        "opponent_spec": scenario.opponent_spec,
        "environment_seed": scenario.seed,
        "source": scenario.source,
        "metadata": scenario.metadata,
        "termination_rule": "glee.tournament.runner.run_episode@factorial-v1",
        "scoring_rule": "terminal-normalized-candidate-payoff@factorial-v1",
    }


def _stream_hash(scenario_id: str, name: str, seed: int) -> str:
    return _hash({"scenario_id": scenario_id, "stream": name, "seed": seed})


def _unlabeled_episode_record(episode: EpisodeResult) -> dict[str, Any]:
    """Episode evidence with arm/treatment identity absent by construction."""

    return {
        "scenario": episode.scenario,
        "candidate_agent_id": episode.candidate_agent_id,
        "opponent_spec": episode.opponent_spec,
        "full_transcript": episode.full_transcript,
        "decision_records": episode.decision_records,
        "terminal_outcome": episode.terminal_outcome,
        "candidate_payoff": episode.candidate_payoff,
        "opponent_payoff": episode.opponent_payoff,
        "metrics": episode.metrics,
        "failure_diagnostics": episode.failure_diagnostics,
    }


def _validate_arm_definitions(factories: Mapping[str, AgentFactory]) -> None:
    if set(factories) != set(FACTORIAL_ARMS):
        raise ValueError(f"factorial evaluator requires exactly {FACTORIAL_ARMS}")


def _assert_paired_manifests(results: list[ArmResult]) -> None:
    paired_fields = (
        "scenario_hash",
        "initial_state_hash",
        "support_mask_hash",
        "eligibility_hash",
        "environment_stream_hash",
        "opponent_stream_hash",
        "economic_stream_hash",
    )
    for field in paired_fields:
        values = {getattr(result, field) for result in results}
        if len(values) != 1:
            raise FactorialIntegrityError(f"arm-dependent {field}: {sorted(values)}")


def run_factorial(
    factories: Mapping[str, AgentFactory],
    *,
    families: list[str],
    games: int,
    seed: int,
    population: OpponentPopulation | None = None,
    catalogue: ConfigCatalogue | None = None,
    support_mask_fn: MaskFactory | None = None,
    eligibility_fn: MaskFactory | None = None,
    scenario_factory: ScenarioFactory | None = None,
    require_inert_parity: bool = False,
) -> list[FactorialRow]:
    """Run four arms on one frozen scenario manifest per paired row.

    Factories receive named seeds.  Economic, environment, opponent, e-process,
    and language streams are derived independently of arm order.  A candidate is
    freshly instantiated per scenario, preventing treatment-specific state or RNG
    consumption from leaking into later paired rows.

    ``require_inert_parity`` is the hard canary mode.  It is used for treatment-off
    wrappers and deliberately inert treatments; every unlabeled episode record must
    then be identical or the row is rejected before an effect is reported.
    """

    _validate_arm_definitions(factories)
    if not families or games < 1:
        raise ValueError("families must be nonempty and games must be positive")
    unknown = sorted(set(families) - set(FAMILY_ROLES))
    if unknown:
        raise ValueError(f"unsupported families: {unknown}")

    support_mask_fn = support_mask_fn or (lambda scenario: {})
    eligibility_fn = eligibility_fn or (lambda scenario: {"language_eligible": False})
    family_counts = {family: 0 for family in families}
    rows: list[FactorialRow] = []

    for index in range(games):
        family = families[index % len(families)]
        family_index = family_counts[family]
        family_counts[family] += 1
        roles = FAMILY_ROLES[family]
        candidate_role = roles[family_index % len(roles)]
        scenario_seed = _scenario_seed(seed, family, family_index)
        if scenario_factory is None:
            scenario = sample_scenario(
                family,
                seed=scenario_seed,
                candidate_role=candidate_role,
                population=population,
                catalogue=catalogue,
            )
        else:
            scenario = scenario_factory(family, scenario_seed, candidate_role)
        if scenario.game_family != family or scenario.candidate_role != candidate_role:
            raise FactorialIntegrityError("scenario factory changed family or balanced role")

        frozen_scenario = copy.deepcopy(scenario)
        scenario_hash = _hash(frozen_scenario)
        initial_state_hash = _hash(_initial_state_manifest(frozen_scenario))
        support_mask = copy.deepcopy(support_mask_fn(copy.deepcopy(frozen_scenario)))
        eligibility = copy.deepcopy(eligibility_fn(copy.deepcopy(frozen_scenario)))
        support_mask_hash = _hash(support_mask)
        eligibility_hash = _hash(eligibility)

        common = {
            "scenario_id": frozen_scenario.scenario_id,
            "economic_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-economic"),
            "eprocess_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-eprocess"),
            "language_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-language"),
            "environment_seed": int(frozen_scenario.seed),
            "opponent_seed": int(frozen_scenario.opponent_spec.get("seed", 0)),
        }
        arm_results: list[ArmResult] = []
        for arm in FACTORIAL_ARMS:
            use_eprocess, use_language = ARM_FLAGS[arm]
            context = ArmContext(
                arm=arm,
                use_eprocess=use_eprocess,
                use_language=use_language,
                **common,
            )
            arm_scenario = copy.deepcopy(frozen_scenario)
            if _hash(arm_scenario) != scenario_hash:
                raise FactorialIntegrityError("scenario copy changed before episode")
            agent = factories[arm](context)
            episode = run_episode(arm_scenario, agent)
            if _hash(arm_scenario) != scenario_hash:
                raise FactorialIntegrityError(f"arm {arm} mutated its scenario")
            unlabeled = _unlabeled_episode_record(episode)
            arm_results.append(
                ArmResult(
                    arm=arm,
                    use_eprocess=use_eprocess,
                    use_language=use_language,
                    candidate_payoff=float(episode.candidate_payoff),
                    opponent_payoff=float(episode.opponent_payoff),
                    scenario_hash=scenario_hash,
                    initial_state_hash=initial_state_hash,
                    support_mask_hash=support_mask_hash,
                    eligibility_hash=eligibility_hash,
                    environment_stream_hash=_stream_hash(frozen_scenario.scenario_id, "environment", context.environment_seed),
                    opponent_stream_hash=_stream_hash(frozen_scenario.scenario_id, "opponent", context.opponent_seed),
                    economic_stream_hash=_stream_hash(frozen_scenario.scenario_id, "candidate-economic", context.economic_seed),
                    episode_hash=_hash(episode),
                    unlabeled_record_hash=_hash(unlabeled),
                    episode=episode,
                )
            )

        _assert_paired_manifests(arm_results)
        if require_inert_parity and len({item.unlabeled_record_hash for item in arm_results}) != 1:
            raise FactorialIntegrityError(
                f"inert treatment changed an unlabeled episode in {frozen_scenario.scenario_id}"
            )
        rows.append(
            FactorialRow(
                key=f"{family}:{frozen_scenario.scenario_id}:{candidate_role}",
                family=family,
                candidate_role=candidate_role,
                scenario_hash=scenario_hash,
                initial_state_hash=initial_state_hash,
                support_mask=support_mask,
                support_mask_hash=support_mask_hash,
                eligibility=eligibility,
                eligibility_hash=eligibility_hash,
                arms=tuple(arm_results),
            )
        )
    return rows


def integrity_certificate(rows: list[FactorialRow]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot certify an empty factorial run")
    for row in rows:
        _assert_paired_manifests(list(row.arms))
    return {
        "schema": "glee.factorial.integrity.v1",
        "rows": len(rows),
        "families": sorted({row.family for row in rows}),
        "roles": sorted({f"{row.family}:{row.candidate_role}" for row in rows}),
        "scenario_manifest_sha256": _hash(
            [
                {
                    "key": row.key,
                    "scenario_hash": row.scenario_hash,
                    "initial_state_hash": row.initial_state_hash,
                    "support_mask_hash": row.support_mask_hash,
                    "eligibility_hash": row.eligibility_hash,
                }
                for row in rows
            ]
        ),
        "arm_order": list(FACTORIAL_ARMS),
        "paired_manifest_fields_identical": True,
    }
