"""Four-arm paired evaluator with explicit treatment-isolation provenance.

This module is research infrastructure.  It does not define either treatment and
does not authorize a payoff experiment.  Its job is to make the pairing contract
executable before an arm is allowed to enter the frozen 2x2 study.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass, replace
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


class RandomStreamCapability:
    """A single named RNG capability with an auditable draw transcript.

    The capability deliberately exposes no seed-reset or underlying ``Random``
    object.  Treatment objects receive only their own capability, so ordinary
    composition cannot accidentally consume the economic stream.
    """

    __slots__ = ("name", "owner", "seed", "_rng", "_trace")

    def __init__(self, name: str, owner: str, seed: int) -> None:
        self.name = name
        self.owner = owner
        self.seed = int(seed)
        self._rng = random.Random(self.seed)
        self._trace: list[dict[str, Any]] = []

    def _record(self, method: str, value: Any, arguments: Any) -> Any:
        self._trace.append(
            {
                "index": len(self._trace),
                "method": method,
                "arguments": arguments,
                "value": value,
            }
        )
        return value

    def random(self) -> float:
        return self._record("random", self._rng.random(), [])

    def randrange(self, stop: int) -> int:
        if int(stop) <= 0:
            raise ValueError("stop must be positive")
        return self._record("randrange", self._rng.randrange(int(stop)), [int(stop)])

    def choice(self, values: tuple[Any, ...] | list[Any]) -> Any:
        items = tuple(values)
        if not items:
            raise IndexError("cannot choose from an empty sequence")
        index = self.randrange(len(items))
        return items[index]

    def audit(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "owner": self.owner,
            "seed_hash": _hash({"stream": self.name, "seed": self.seed}),
            "draws": len(self._trace),
            "trace_sha256": _hash(self._trace),
        }


class CandidateRandomness:
    """Capability-separated candidate RNG streams for one arm and scenario."""

    _OWNER_STREAM = {
        "economic_policy": "economic",
        "eprocess_treatment": "eprocess",
        "language_treatment": "language",
    }

    def __init__(
        self,
        *,
        scenario_id: str,
        economic_seed: int,
        eprocess_seed: int,
        language_seed: int,
        use_eprocess: bool,
        use_language: bool,
    ) -> None:
        self.scenario_id = str(scenario_id)
        self._seeds = {
            "economic": int(economic_seed),
            "eprocess": int(eprocess_seed),
            "language": int(language_seed),
        }
        self._enabled = {
            "economic": True,
            "eprocess": bool(use_eprocess),
            "language": bool(use_language),
        }
        self._claims: dict[str, RandomStreamCapability] = {}

    def claim(self, owner: str, stream: str | None = None) -> RandomStreamCapability:
        expected = self._OWNER_STREAM.get(str(owner))
        requested = str(stream or expected or "")
        if expected is None:
            raise FactorialIntegrityError(f"unknown RNG capability owner: {owner}")
        if requested != expected:
            raise FactorialIntegrityError(
                f"{owner} may access only the {expected} stream, not {requested}"
            )
        if not self._enabled[expected]:
            raise FactorialIntegrityError(f"{owner} requested disabled {expected} treatment stream")
        prior = self._claims.get(owner)
        if prior is not None:
            return prior
        capability = RandomStreamCapability(expected, owner, self._seeds[expected])
        self._claims[owner] = capability
        return capability

    def seed_manifest(self) -> dict[str, int]:
        return dict(self._seeds)

    def audit(self) -> dict[str, Any]:
        return {
            "schema": "glee.factorial.candidate_randomness.v2",
            "scenario_id": self.scenario_id,
            "enabled": dict(self._enabled),
            "claims": {
                owner: capability.audit()
                for owner, capability in sorted(self._claims.items())
            },
        }

    def validate_complete(self) -> dict[str, Any]:
        expected = {"economic_policy"}
        if self._enabled["eprocess"]:
            expected.add("eprocess_treatment")
        if self._enabled["language"]:
            expected.add("language_treatment")
        observed = set(self._claims)
        if observed != expected:
            raise FactorialIntegrityError(
                f"candidate RNG claims differ from enabled treatments: expected {sorted(expected)}, "
                f"observed {sorted(observed)}"
            )
        return self.audit()

    def validate_bindings(self, bindings: Mapping[str, Any]) -> None:
        expected = set(self._claims)
        if set(bindings) != expected:
            raise FactorialIntegrityError(
                f"agent capability bindings differ from claims: expected {sorted(expected)}, "
                f"observed {sorted(bindings)}"
            )
        for owner in expected:
            if bindings[owner] is not self._claims[owner]:
                raise FactorialIntegrityError(f"agent did not bind {owner} to its issued capability")


@dataclass(frozen=True)
class ArmContext:
    arm: str
    use_eprocess: bool
    use_language: bool
    scenario_id: str
    randomness: CandidateRandomness

    def seed_manifest(self) -> dict[str, int]:
        return self.randomness.seed_manifest()


@dataclass(frozen=True)
class ArmResult:
    arm: str
    use_eprocess: bool
    use_language: bool
    candidate_payoff: float
    opponent_payoff: float
    scenario_hash: str
    initial_state_hash: str
    configuration_hash: str
    opponent_identity_hash: str
    role_identity_hash: str
    support_mask_hash: str
    support_identity_hash: str
    eligibility_hash: str
    environment_stream_hash: str
    nature_stream_hash: str
    nature_trace_hash: str
    opponent_stream_hash: str
    economic_stream_hash: str
    artifact_provenance_hash: str
    artifact_provenance: dict[str, Any]
    randomness_audit_hash: str
    randomness_audit: dict[str, Any]
    episode_hash: str
    unlabeled_record_hash: str
    non_language_record_hash: str
    non_eprocess_record_hash: str
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
    payload = f"glee.factorial.v2|{master_seed}|{scenario_id}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


def _scenario_seed(master_seed: int, family: str, family_index: int) -> int:
    payload = f"glee.factorial.v2|{master_seed}|scenario|{family}|{family_index}".encode("utf-8")
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
        "termination_rule": "glee.tournament.runner.run_episode@factorial-v2",
        "scoring_rule": "terminal-normalized-candidate-payoff@factorial-v2",
    }


def _stream_hash(scenario_id: str, name: str, seed: int) -> str:
    return _hash({"scenario_id": scenario_id, "stream": name, "seed": seed})


def factorial_named_seed(master_seed: int, scenario_id: str, stream: str) -> int:
    """Public verifier surface for the evaluator's frozen named substreams."""

    return _named_seed(master_seed, scenario_id, stream)


def factorial_scenario_seed(master_seed: int, family: str, family_index: int) -> int:
    """Public verifier surface for the pre-outcome scenario stream."""

    return _scenario_seed(master_seed, family, family_index)


def factorial_stream_hash(scenario_id: str, name: str, seed: int) -> str:
    """Public verifier surface for an environment/opponent stream identity."""

    return _stream_hash(scenario_id, name, seed)


def nature_trace(episode: EpisodeResult) -> list[dict[str, Any]]:
    """Return only engine-owned nature events, in transcript order.

    Treatment-rendering fields never enter this projection.  It therefore binds
    the declared nature stream to the evidence that was actually consumed by an
    episode rather than merely comparing four caller-supplied hash strings.
    """

    trace: list[dict[str, Any]] = []
    for item in episode.full_transcript:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        action_type = str(item.get("action_type") or "").strip().lower()
        if role == "nature" or action_type.startswith("nature_"):
            trace.append(copy.deepcopy(item))
    return trace


def _unlabeled_episode_record(episode: EpisodeResult) -> dict[str, Any]:
    """Episode evidence with arm/treatment identity absent by construction."""

    return {
        "scenario": episode.scenario,
        "opponent_spec": episode.opponent_spec,
        "full_transcript": episode.full_transcript,
        "decision_records": episode.decision_records,
        "terminal_outcome": episode.terminal_outcome,
        "candidate_payoff": episode.candidate_payoff,
        "opponent_payoff": episode.opponent_payoff,
        "metrics": episode.metrics,
        "failure_diagnostics": episode.failure_diagnostics,
    }


def _treatment_projection(value: Any, treatment: str) -> Any:
    """Remove only a declared treatment's rendering/audit fields.

    The projection is used by canaries, not by payoff scoring.  Economic
    decisions, opponent actions, nature outcomes, termination, and payoffs stay
    present, so direct RNG contamination still changes the hash.
    """

    payload = to_jsonable(value)

    def walk(item: Any) -> Any:
        if isinstance(item, list):
            return [walk(child) for child in item]
        if not isinstance(item, dict):
            return item
        action_type = str(item.get("action_type") or "")
        out: dict[str, Any] = {}
        for key, child in item.items():
            if key == "candidate_agent_id":
                continue
            if treatment == "language" and key in {
                "message",
                "free_text_message",
                "language_treatment",
            }:
                continue
            if treatment == "language" and key == "raw_text" and action_type in {
                "message",
                "recommendation",
            }:
                continue
            if treatment == "eprocess" and key == "eprocess_treatment":
                continue
            out[str(key)] = walk(child)
        return out

    return walk(payload)


def _validate_arm_definitions(factories: Mapping[str, AgentFactory]) -> None:
    if set(factories) != set(FACTORIAL_ARMS):
        raise ValueError(f"factorial evaluator requires exactly {FACTORIAL_ARMS}")


def _assert_paired_manifests(results: list[ArmResult]) -> None:
    paired_fields = (
        "scenario_hash",
        "initial_state_hash",
        "configuration_hash",
        "opponent_identity_hash",
        "role_identity_hash",
        "support_mask_hash",
        "support_identity_hash",
        "eligibility_hash",
        "environment_stream_hash",
        "nature_stream_hash",
        "nature_trace_hash",
        "opponent_stream_hash",
        "economic_stream_hash",
        "artifact_provenance_hash",
    )
    for field in paired_fields:
        values = {getattr(result, field) for result in results}
        if len(values) != 1:
            raise FactorialIntegrityError(f"arm-dependent {field}: {sorted(values)}")


def _claim_audit(result: ArmResult, owner: str) -> dict[str, Any] | None:
    value = (result.randomness_audit.get("claims") or {}).get(owner)
    return value if isinstance(value, dict) else None


def _assert_active_isolation_canary(results: list[ArmResult]) -> None:
    by_arm = {result.arm: result for result in results}
    for left_name, right_name in (("e0_l0", "e0_l1"), ("e1_l0", "e1_l1")):
        left, right = by_arm[left_name], by_arm[right_name]
        if left.non_language_record_hash != right.non_language_record_hash:
            raise FactorialIntegrityError(
                f"language treatment changed a non-language trajectory: {left_name}/{right_name}"
            )
        if _claim_audit(left, "economic_policy") != _claim_audit(right, "economic_policy"):
            raise FactorialIntegrityError(
                f"language treatment perturbed economic RNG trace: {left_name}/{right_name}"
            )
    for left_name, right_name in (("e0_l0", "e1_l0"), ("e0_l1", "e1_l1")):
        left, right = by_arm[left_name], by_arm[right_name]
        if left.non_eprocess_record_hash != right.non_eprocess_record_hash:
            raise FactorialIntegrityError(
                f"inert e-process changed an economic trajectory: {left_name}/{right_name}"
            )
        if _claim_audit(left, "economic_policy") != _claim_audit(right, "economic_policy"):
            raise FactorialIntegrityError(
                f"e-process treatment perturbed economic RNG trace: {left_name}/{right_name}"
            )


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
    require_active_isolation_canary: bool = False,
    required_artifact_provenance: Mapping[str, Any] | None = None,
) -> list[FactorialRow]:
    """Run four arms on one frozen scenario manifest per paired row.

    Scenario, environment, opponent, economic, e-process, and language streams
    are named and independently derived. Candidate factories receive only the
    three capability-separated candidate streams; environment/opponent seeds
    remain inside the frozen scenario. A candidate is freshly instantiated per
    arm and scenario.

    ``require_inert_parity`` is the hard canary mode.  It is used for treatment-off
    wrappers and deliberately inert treatments; every unlabeled episode record must
    then be identical or the row is rejected before an effect is reported.

    When ``required_artifact_provenance`` is supplied, every arm must expose
    ``factorial_artifact_provenance()`` and its canonical payload must exactly match
    the frozen contract. This prevents any arm from silently dropping or replacing
    the shared Model-C/support bytes.
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
    seen_scenario_ids: set[str] = set()

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

        if scenario.scenario_id in seen_scenario_ids:
            raise FactorialIntegrityError(f"duplicate scenario_id: {scenario.scenario_id}")
        seen_scenario_ids.add(scenario.scenario_id)

        environment_seed = _named_seed(seed, scenario.scenario_id, "environment")
        opponent_seed = _named_seed(seed, scenario.scenario_id, "opponent-policy")
        opponent_spec = copy.deepcopy(scenario.opponent_spec)
        opponent_spec["seed"] = opponent_seed
        metadata = copy.deepcopy(scenario.metadata)
        metadata["factorial_randomness"] = {
            "schema": "glee.factorial.stream_manifest.v2",
            "master_seed_hash": _hash({"master_seed": int(seed)}),
            "scenario_seed_hash": _stream_hash(scenario.scenario_id, "scenario", scenario_seed),
            "environment_seed_hash": _stream_hash(scenario.scenario_id, "environment", environment_seed),
            "opponent_seed_hash": _stream_hash(scenario.scenario_id, "opponent-policy", opponent_seed),
        }
        frozen_scenario = replace(
            copy.deepcopy(scenario),
            seed=environment_seed,
            opponent_spec=opponent_spec,
            metadata=metadata,
        )
        scenario_hash = _hash(frozen_scenario)
        initial_state_hash = _hash(_initial_state_manifest(frozen_scenario))
        configuration_hash = _hash(
            {
                "config_id": frozen_scenario.config_id,
                "public_parameters": frozen_scenario.public_parameters,
            }
        )
        opponent_identity_hash = _hash(
            {
                "opponent_role": frozen_scenario.opponent_role,
                "opponent_spec": frozen_scenario.opponent_spec,
            }
        )
        role_identity_hash = _hash(
            {
                "candidate_role": frozen_scenario.candidate_role,
                "opponent_role": frozen_scenario.opponent_role,
            }
        )
        support_mask = copy.deepcopy(support_mask_fn(copy.deepcopy(frozen_scenario)))
        eligibility = copy.deepcopy(eligibility_fn(copy.deepcopy(frozen_scenario)))
        support_mask_hash = _hash(support_mask)
        eligibility_hash = _hash(eligibility)

        candidate_seeds = {
            "economic_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-economic"),
            "eprocess_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-eprocess"),
            "language_seed": _named_seed(seed, frozen_scenario.scenario_id, "candidate-language"),
        }
        arm_results: list[ArmResult] = []
        for arm in FACTORIAL_ARMS:
            use_eprocess, use_language = ARM_FLAGS[arm]
            randomness = CandidateRandomness(
                scenario_id=frozen_scenario.scenario_id,
                use_eprocess=use_eprocess,
                use_language=use_language,
                **candidate_seeds,
            )
            context = ArmContext(
                arm=arm,
                use_eprocess=use_eprocess,
                use_language=use_language,
                scenario_id=frozen_scenario.scenario_id,
                randomness=randomness,
            )
            arm_scenario = copy.deepcopy(frozen_scenario)
            if _hash(arm_scenario) != scenario_hash:
                raise FactorialIntegrityError("scenario copy changed before episode")
            agent = factories[arm](context)
            artifact_fn = getattr(agent, "factorial_artifact_provenance", None)
            if callable(artifact_fn):
                artifact_provenance = to_jsonable(artifact_fn())
            else:
                artifact_provenance = {"schema": "glee.factorial.artifacts.absent.v1"}
            if required_artifact_provenance is not None:
                if not callable(artifact_fn):
                    raise FactorialIntegrityError(
                        f"arm {arm} lacks factorial_artifact_provenance()"
                    )
                if _hash(artifact_provenance) != _hash(required_artifact_provenance):
                    raise FactorialIntegrityError(
                        f"arm {arm} artifact provenance differs from the frozen contract"
                    )
            support_identity_hash = _hash(
                {
                    "support_mask_hash": support_mask_hash,
                    "support_index": artifact_provenance.get("support_index"),
                }
            )
            binding_fn = getattr(agent, "factorial_capability_bindings", None)
            if not callable(binding_fn):
                raise FactorialIntegrityError(
                    f"arm {arm} agent lacks factorial_capability_bindings()"
                )
            randomness.validate_bindings(binding_fn())
            episode = run_episode(arm_scenario, agent)
            randomness_audit = randomness.validate_complete()
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
                    configuration_hash=configuration_hash,
                    opponent_identity_hash=opponent_identity_hash,
                    role_identity_hash=role_identity_hash,
                    support_mask_hash=support_mask_hash,
                    support_identity_hash=support_identity_hash,
                    eligibility_hash=eligibility_hash,
                    environment_stream_hash=_stream_hash(
                        frozen_scenario.scenario_id, "environment", environment_seed
                    ),
                    nature_stream_hash=_stream_hash(
                        frozen_scenario.scenario_id, "environment", environment_seed
                    ),
                    nature_trace_hash=_hash(nature_trace(episode)),
                    opponent_stream_hash=_stream_hash(frozen_scenario.scenario_id, "opponent-policy", opponent_seed),
                    economic_stream_hash=_stream_hash(
                        frozen_scenario.scenario_id,
                        "candidate-economic",
                        candidate_seeds["economic_seed"],
                    ),
                    artifact_provenance_hash=_hash(artifact_provenance),
                    artifact_provenance=artifact_provenance,
                    randomness_audit_hash=_hash(randomness_audit),
                    randomness_audit=randomness_audit,
                    episode_hash=_hash(episode),
                    unlabeled_record_hash=_hash(unlabeled),
                    non_language_record_hash=_hash(_treatment_projection(episode, "language")),
                    non_eprocess_record_hash=_hash(_treatment_projection(episode, "eprocess")),
                    episode=episode,
                )
            )

        _assert_paired_manifests(arm_results)
        if require_active_isolation_canary:
            _assert_active_isolation_canary(arm_results)
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
        "schema": "glee.factorial.integrity.v2",
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
