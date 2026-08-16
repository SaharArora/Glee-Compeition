"""Frozen paired-report construction and validation for the research 2x2 study.

This module does not run episodes.  It accepts already-paired ``FactorialRow``
objects, fails closed on integrity/provenance defects, and reconstructs the
declared estimands and multiplicity decision from compact row evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import NormalDist, mean, variance
from typing import Any, Iterable, Mapping, Sequence

from glee_eval.data.schemas import Scenario, to_jsonable
from glee_eval.experiments.factorial import (
    ARM_FLAGS,
    FACTORIAL_ARMS,
    FAMILY_ROLES,
    ArmResult,
    FactorialRow,
    factorial_named_seed,
    factorial_stream_hash,
    nature_trace,
)
from glee_eval.response_models.runtime import GLOBAL_KEYS, persuasion_keys


CONTRASTS = ("eprocess_main_effect", "language_main_effect", "interaction")
ELIGIBILITY_FIELDS = (
    "eprocess_eligible",
    "language_eligible",
    "joint_eligible",
    "eprocess_negative_control",
    "language_negative_control",
)
ELIGIBILITY_SCHEMA = "glee.research.factorial_eligibility.v1"
PRODUCTION_CONTRACT_SCHEMA = "glee.research.factorial_report_contract.production.v2"
SYNTHETIC_CONTRACT_SCHEMA = "glee.research.factorial_report_contract.synthetic.v1"
PRODUCTION_VALIDATION_SCHEMA = "glee.research.factorial_report_validation.production.v2"
SYNTHETIC_VALIDATION_SCHEMA = "glee.research.factorial_report_validation.synthetic.v1"
FROZEN_EXPECTED_ROWS = 3600
FROZEN_FAMILY_COUNTS = (
    ("bargaining", 1200),
    ("negotiation", 1200),
    ("persuasion", 1200),
)
FROZEN_MASTER_SEED = 20260829
FROZEN_ALPHA = 0.05
# No production contract is authorized until the user selects the language
# receiver environment and the resulting 3,600-row pre-outcome manifest is
# frozen.  This fail-closed pin prevents an arbitrary caller from manufacturing
# a different 3,600-row "production" study with plausible-looking hashes.
AUTHORIZED_PRODUCTION_CONTRACT_SHA256: str | None = None
ELIGIBILITY_DERIVATION_SPEC = {
    "schema": "glee.research.factorial_eligibility_derivation.v2",
    "eprocess_scope": "persuasion_candidate_seller_with_later_turn_and_any_supported_non_global_model_c_follow_reference",
    "model_c_min_support": "artifact.min_support",
    "model_c_min_support_quality": 0.5,
    "model_c_probability_interval": [0.01, 0.99],
    "language_scope": "receiver_contract_delivers_and_consumes_candidate_text",
    "joint": "eprocess_eligible_and_language_eligible",
    "negative_controls": "boolean_complements",
    "forbidden_inputs": ["candidate_payoff", "opponent_payoff", "terminal_outcome", "arm_action"],
}
PRIMARY_HYPOTHESES = (
    ("eprocess", "eprocess_eligible", "eprocess_main_effect"),
    ("language", "language_eligible", "language_main_effect"),
    ("interaction", "joint_eligible", "interaction"),
)


class FactorialReportError(RuntimeError):
    """Raised before reporting when frozen paired evidence is invalid."""


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_artifact_json(provenance: Mapping[str, Any], key: str) -> dict[str, Any]:
    descriptor = provenance.get(key)
    if not isinstance(descriptor, dict) or set(descriptor) != {"path", "sha256"}:
        raise FactorialReportError(f"frozen artifact {key} descriptor is malformed")
    path = Path(str(descriptor.get("path") or ""))
    expected = str(descriptor.get("sha256") or "")
    if not _is_sha256(expected) or not path.is_file():
        raise FactorialReportError(f"frozen artifact {key} is unavailable")
    actual = _file_sha256(path)
    if actual != expected:
        raise FactorialReportError(f"frozen artifact {key} byte hash mismatch")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise FactorialReportError(f"frozen artifact {key} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FactorialReportError(f"frozen artifact {key} must contain an object")
    return value


def _receiver_contract(provenance: Mapping[str, Any]) -> dict[str, Any]:
    value = provenance.get("receiver_contract")
    required = {
        "schema",
        "environment_id",
        "candidate_text_delivered",
        "receiver_consumes_candidate_text",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise FactorialReportError("frozen receiver-capability contract is malformed")
    if value.get("schema") != "glee.research.receiver_capability.v1":
        raise FactorialReportError("frozen receiver-capability schema mismatch")
    if type(value.get("candidate_text_delivered")) is not bool or type(
        value.get("receiver_consumes_candidate_text")
    ) is not bool:
        raise FactorialReportError("receiver-capability flags must be booleans")
    return dict(value)


def _horizon(parameters: Mapping[str, Any]) -> int:
    value = parameters.get("total_rounds", parameters.get("max_rounds", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def derive_factorial_eligibility(
    scenario: Scenario,
    *,
    model_c: Mapping[str, Any],
    receiver_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive immutable eligibility from pre-arm state and frozen artifacts only."""

    eprocess = False
    horizon = _horizon(scenario.public_parameters)
    if (
        scenario.game_family == "persuasion"
        and scenario.candidate_role == "seller"
        and horizon >= 2
    ):
        family = (model_c.get("families") or {}).get("persuasion") or {}
        buckets = family.get("buckets") or {}
        min_support = int(model_c.get("min_support", 30) or 30)
        source = scenario.source or "synthetic"
        messages = (None, "I recommend buying.", "This product might be suitable.")
        for round_number in range(1, horizon):
            state = {
                "configuration": dict(scenario.public_parameters),
                "round": round_number,
                "source": source,
            }
            for recommendation in ("yes", "no"):
                for quality in ("high-quality", "low-quality", None):
                    for message in messages:
                        for key in persuasion_keys(state, recommendation, quality, message):
                            if key in GLOBAL_KEYS:
                                continue
                            bucket = buckets.get(key)
                            if not isinstance(bucket, dict):
                                continue
                            probability = float(bucket.get("probability", 0.5))
                            support = int(bucket.get("trials", 0) or 0)
                            support_quality = float(bucket.get("support_quality", 0.0))
                            if (
                                support >= min_support
                                and support_quality >= 0.5
                                and 0.01 <= probability <= 0.99
                            ):
                                eprocess = True
                                break
                        if eprocess:
                            break
                    if eprocess:
                        break
                if eprocess:
                    break
            if eprocess:
                break
    language = bool(
        receiver_contract.get("candidate_text_delivered")
        and receiver_contract.get("receiver_consumes_candidate_text")
        and scenario.game_family == "persuasion"
        and scenario.candidate_role == "seller"
        and str(scenario.public_parameters.get("seller_message_type") or "") == "text"
    )
    return {
        "schema": ELIGIBILITY_SCHEMA,
        "eprocess_eligible": eprocess,
        "language_eligible": language,
        "joint_eligible": eprocess and language,
        "eprocess_negative_control": not eprocess,
        "language_negative_control": not language,
    }


def _expected_episode_opponent_spec(scenario: Scenario) -> dict[str, Any]:
    value = scenario.opponent_spec
    return {
        "archetype": value.get("archetype", "unknown"),
        "game_family": scenario.game_family,
        "parameters": value.get("parameters", {}),
        "seed": int(value.get("seed", 0)),
        "version": value.get("version", "0.1"),
        "description": value.get("description", ""),
    }


def _expected_rng_seed_hash(master_seed: int, scenario_id: str, owner: str) -> str:
    stream_names = {
        "economic_policy": ("candidate-economic", "economic"),
        "eprocess_treatment": ("candidate-eprocess", "eprocess"),
        "language_treatment": ("candidate-language", "language"),
    }
    seed_stream, capability_stream = stream_names[owner]
    seed = factorial_named_seed(master_seed, scenario_id, seed_stream)
    return canonical_hash({"stream": capability_stream, "seed": seed})


@dataclass(frozen=True)
class FactorialReportContract:
    expected_rows: int = FROZEN_EXPECTED_ROWS
    expected_family_counts: tuple[tuple[str, int], ...] = FROZEN_FAMILY_COUNTS
    master_seed: int = FROZEN_MASTER_SEED
    alpha: float = FROZEN_ALPHA
    minimum_cell_rows: int = 2
    required_artifact_provenance_hash: str | None = None
    research_question_sha256: str | None = None
    config_catalogue_sha256: str | None = None
    opponent_population_sha256: str | None = None
    scenario_manifest_sha256: str | None = None
    evaluator_code_sha256: str | None = None
    agent_entrypoints_sha256: str | None = None
    execution_command_sha256: str | None = None
    eligibility_derivation_sha256: str | None = None
    schema: str = PRODUCTION_CONTRACT_SCHEMA

    @classmethod
    def synthetic(
        cls,
        *,
        rows_per_family: int,
        master_seed: int = FROZEN_MASTER_SEED,
        minimum_cell_rows: int = 2,
        required_artifact_provenance_hash: str | None = None,
        research_question_sha256: str | None = None,
    ) -> "FactorialReportContract":
        """Construct a visibly non-production contract for bounded unit fixtures."""

        return cls(
            expected_rows=int(rows_per_family) * len(FROZEN_FAMILY_COUNTS),
            expected_family_counts=tuple(
                (family, int(rows_per_family)) for family, _ in FROZEN_FAMILY_COUNTS
            ),
            master_seed=int(master_seed),
            minimum_cell_rows=int(minimum_cell_rows),
            required_artifact_provenance_hash=required_artifact_provenance_hash,
            research_question_sha256=research_question_sha256,
            schema=SYNTHETIC_CONTRACT_SCHEMA,
        )

    @property
    def is_production(self) -> bool:
        return self.schema == PRODUCTION_CONTRACT_SCHEMA

    @property
    def family_counts(self) -> dict[str, int]:
        return dict(self.expected_family_counts)

    @property
    def master_seed_hash(self) -> str:
        return canonical_hash({"master_seed": self.master_seed})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "expected_rows": self.expected_rows,
            "expected_family_counts": self.family_counts,
            "master_seed": self.master_seed,
            "master_seed_hash": self.master_seed_hash,
            "alpha": self.alpha,
            "minimum_cell_rows": self.minimum_cell_rows,
            "required_artifact_provenance_hash": self.required_artifact_provenance_hash,
            "research_question_sha256": self.research_question_sha256,
            "config_catalogue_sha256": self.config_catalogue_sha256,
            "opponent_population_sha256": self.opponent_population_sha256,
            "scenario_manifest_sha256": self.scenario_manifest_sha256,
            "evaluator_code_sha256": self.evaluator_code_sha256,
            "agent_entrypoints_sha256": self.agent_entrypoints_sha256,
            "execution_command_sha256": self.execution_command_sha256,
            "eligibility_derivation_sha256": self.eligibility_derivation_sha256,
            "eligibility_fields": list(ELIGIBILITY_FIELDS),
            "primary_hypotheses": [list(item) for item in PRIMARY_HYPOTHESES],
            "uncertainty": "paired_scenario_normal_equal_family_weighted",
            "multiplicity": "holm_step_down_two_sided_normal_p_alpha_0.05",
        }

    def validate_production_freeze(self) -> None:
        if self.schema != PRODUCTION_CONTRACT_SCHEMA:
            raise FactorialReportError("production validation requires the production contract schema")
        exact = {
            "expected_rows": (self.expected_rows, FROZEN_EXPECTED_ROWS),
            "family_counts": (self.expected_family_counts, FROZEN_FAMILY_COUNTS),
            "master_seed": (self.master_seed, FROZEN_MASTER_SEED),
            "alpha": (self.alpha, FROZEN_ALPHA),
            "minimum_cell_rows": (self.minimum_cell_rows, 2),
        }
        changed = [name for name, (observed, expected) in exact.items() if observed != expected]
        if changed:
            raise FactorialReportError(f"production contract changed frozen fields: {changed}")
        required_hashes = {
            "required_artifact_provenance_hash": self.required_artifact_provenance_hash,
            "research_question_sha256": self.research_question_sha256,
            "config_catalogue_sha256": self.config_catalogue_sha256,
            "opponent_population_sha256": self.opponent_population_sha256,
            "scenario_manifest_sha256": self.scenario_manifest_sha256,
            "evaluator_code_sha256": self.evaluator_code_sha256,
            "agent_entrypoints_sha256": self.agent_entrypoints_sha256,
            "execution_command_sha256": self.execution_command_sha256,
            "eligibility_derivation_sha256": self.eligibility_derivation_sha256,
        }
        invalid = [name for name, value in required_hashes.items() if not _is_sha256(value)]
        if invalid:
            raise FactorialReportError(f"production contract lacks frozen hashes: {invalid}")
        if self.eligibility_derivation_sha256 != canonical_hash(ELIGIBILITY_DERIVATION_SPEC):
            raise FactorialReportError("production eligibility derivation hash is not the frozen v2 spec")
        if AUTHORIZED_PRODUCTION_CONTRACT_SHA256 is None:
            raise FactorialReportError(
                "no production contract is authorized before language-environment selection "
                "and a frozen pre-outcome scenario manifest"
            )
        if canonical_hash(self.to_dict()) != AUTHORIZED_PRODUCTION_CONTRACT_SHA256:
            raise FactorialReportError("production contract hash is not the authorized frozen study")


def _same_hash(values: Iterable[str], label: str) -> str:
    observed = set(values)
    if len(observed) != 1:
        raise FactorialReportError(f"paired arms differ on {label}: {sorted(observed)}")
    return next(iter(observed))


def _expected_claims(arm: str) -> set[str]:
    use_eprocess, use_language = ARM_FLAGS[arm]
    claims = {"economic_policy"}
    if use_eprocess:
        claims.add("eprocess_treatment")
    if use_language:
        claims.add("language_treatment")
    return claims


def _validate_capability_manifest(
    arm: ArmResult,
    scenario_id: str,
    master_seed: int,
) -> None:
    audit = arm.randomness_audit
    if canonical_hash(audit) != arm.randomness_audit_hash:
        raise FactorialReportError(f"arm {arm.arm} randomness audit hash mismatch")
    if audit.get("schema") != "glee.factorial.candidate_randomness.v2":
        raise FactorialReportError(f"arm {arm.arm} has wrong randomness schema")
    if str(audit.get("scenario_id")) != scenario_id:
        raise FactorialReportError(f"arm {arm.arm} randomness scenario mismatch")
    expected_enabled = {
        "economic": True,
        "eprocess": bool(arm.use_eprocess),
        "language": bool(arm.use_language),
    }
    if audit.get("enabled") != expected_enabled:
        raise FactorialReportError(f"arm {arm.arm} enabled streams mismatch")
    claims = audit.get("claims")
    if not isinstance(claims, dict) or set(claims) != _expected_claims(arm.arm):
        raise FactorialReportError(f"arm {arm.arm} capability claims mismatch")
    stream_by_owner = {
        "economic_policy": "economic",
        "eprocess_treatment": "eprocess",
        "language_treatment": "language",
    }
    for owner, stream in stream_by_owner.items():
        if owner not in claims:
            continue
        row = claims[owner]
        if not isinstance(row, dict) or row.get("owner") != owner or row.get("name") != stream:
            raise FactorialReportError(f"arm {arm.arm} crossed RNG capability {owner}")
        if int(row.get("draws", -1)) < 0:
            raise FactorialReportError(f"arm {arm.arm} has invalid RNG draw count")
        for field in ("seed_hash", "trace_sha256"):
            value = str(row.get(field) or "")
            if not _is_sha256(value):
                raise FactorialReportError(f"arm {arm.arm} has invalid {owner} {field}")
        if row["seed_hash"] != _expected_rng_seed_hash(master_seed, scenario_id, owner):
            raise FactorialReportError(f"arm {arm.arm} has forged {owner} seed provenance")


def _scenario_hashes(scenario: Scenario) -> dict[str, str]:
    return {
        "configuration_hash": canonical_hash(
            {"config_id": scenario.config_id, "public_parameters": scenario.public_parameters}
        ),
        "opponent_identity_hash": canonical_hash(
            {"opponent_role": scenario.opponent_role, "opponent_spec": scenario.opponent_spec}
        ),
        "role_identity_hash": canonical_hash(
            {
                "candidate_role": scenario.candidate_role,
                "opponent_role": scenario.opponent_role,
            }
        ),
    }


def _validate_eligibility(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise FactorialReportError("eligibility must be an object")
    expected_keys = {"schema", *ELIGIBILITY_FIELDS}
    if set(value) != expected_keys or value.get("schema") != ELIGIBILITY_SCHEMA:
        raise FactorialReportError("eligibility schema/fields differ from the frozen contract")
    out: dict[str, bool] = {}
    for field in ELIGIBILITY_FIELDS:
        if type(value.get(field)) is not bool:
            raise FactorialReportError(f"eligibility field {field} must be boolean")
        out[field] = value[field]
    if out["joint_eligible"] != (out["eprocess_eligible"] and out["language_eligible"]):
        raise FactorialReportError("joint eligibility is not the conjunction of treatments")
    if out["eprocess_negative_control"] != (not out["eprocess_eligible"]):
        raise FactorialReportError("e-process negative-control label is inconsistent")
    if out["language_negative_control"] != (not out["language_eligible"]):
        raise FactorialReportError("language negative-control label is inconsistent")
    return out


def _row_digest(row: FactorialRow) -> str:
    return canonical_hash(
        {
            "key": row.key,
            "family": row.family,
            "candidate_role": row.candidate_role,
            "scenario_hash": row.scenario_hash,
            "initial_state_hash": row.initial_state_hash,
            "support_mask_hash": row.support_mask_hash,
            "eligibility_hash": row.eligibility_hash,
            "arms": [
                {
                    "arm": arm.arm,
                    "candidate_payoff": arm.candidate_payoff,
                    "opponent_payoff": arm.opponent_payoff,
                    "episode_hash": arm.episode_hash,
                    "randomness_audit_hash": arm.randomness_audit_hash,
                    "artifact_provenance_hash": arm.artifact_provenance_hash,
                    "configuration_hash": arm.configuration_hash,
                    "opponent_identity_hash": arm.opponent_identity_hash,
                    "role_identity_hash": arm.role_identity_hash,
                    "nature_stream_hash": arm.nature_stream_hash,
                    "nature_trace_hash": arm.nature_trace_hash,
                    "support_identity_hash": arm.support_identity_hash,
                }
                for arm in sorted(row.arms, key=lambda item: item.arm)
            ],
        }
    )


def _preoutcome_manifest_record(record: Mapping[str, Any]) -> dict[str, Any]:
    row: FactorialRow = record["row"]
    arm = sorted(row.arms, key=lambda item: item.arm)[0]
    return {
        "key": row.key,
        "family": row.family,
        "candidate_role": row.candidate_role,
        "scenario": arm.episode.scenario,
        "scenario_hash": row.scenario_hash,
        "initial_state_hash": row.initial_state_hash,
        "configuration_hash": arm.configuration_hash,
        "opponent_identity_hash": arm.opponent_identity_hash,
        "role_identity_hash": arm.role_identity_hash,
        "support_mask": row.support_mask,
        "support_mask_hash": row.support_mask_hash,
        "support_identity_hash": arm.support_identity_hash,
        "eligibility": row.eligibility,
        "eligibility_hash": row.eligibility_hash,
        "environment_stream_hash": arm.environment_stream_hash,
        "opponent_stream_hash": arm.opponent_stream_hash,
        "economic_stream_hash": arm.economic_stream_hash,
        "artifact_provenance_hash": arm.artifact_provenance_hash,
    }


def _validate_row(
    row: FactorialRow,
    contract: FactorialReportContract,
    *,
    model_c: Mapping[str, Any] | None = None,
    receiver_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if len(row.arms) != 4 or {arm.arm for arm in row.arms} != set(FACTORIAL_ARMS):
        raise FactorialReportError(f"row {row.key} does not contain all four arms")
    if len({id(arm) for arm in row.arms}) != 4:
        raise FactorialReportError(f"row {row.key} aliases arm results")
    arms = sorted(row.arms, key=lambda item: item.arm)
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
        _same_hash((str(getattr(arm, field)) for arm in arms), field)
    if row.scenario_hash != arms[0].scenario_hash:
        raise FactorialReportError(f"row {row.key} scenario hash mismatch")
    if row.initial_state_hash != arms[0].initial_state_hash:
        raise FactorialReportError(f"row {row.key} initial-state hash mismatch")
    if row.support_mask_hash != canonical_hash(row.support_mask):
        raise FactorialReportError(f"row {row.key} support mask hash mismatch")
    if row.eligibility_hash != canonical_hash(row.eligibility):
        raise FactorialReportError(f"row {row.key} eligibility hash mismatch")
    eligibility = _validate_eligibility(row.eligibility)
    if contract.is_production:
        if model_c is None or receiver_contract is None:
            raise FactorialReportError("production eligibility inputs were not verified")
        expected_eligibility = derive_factorial_eligibility(
            arms[0].episode.scenario,
            model_c=model_c,
            receiver_contract=receiver_contract,
        )
        if row.eligibility != expected_eligibility:
            raise FactorialReportError(
                f"row {row.key} eligibility does not reconstruct from pre-outcome inputs"
            )
    if contract.required_artifact_provenance_hash is not None:
        if arms[0].artifact_provenance_hash != contract.required_artifact_provenance_hash:
            raise FactorialReportError(f"row {row.key} uses the wrong frozen artifacts")
    for arm in arms:
        expected_flags = ARM_FLAGS[arm.arm]
        if (arm.use_eprocess, arm.use_language) != expected_flags:
            raise FactorialReportError(f"arm {arm.arm} treatment flags mismatch")
        if canonical_hash(arm.artifact_provenance) != arm.artifact_provenance_hash:
            raise FactorialReportError(f"arm {arm.arm} artifact hash mismatch")
        expected_support_identity = canonical_hash(
            {
                "support_mask_hash": arm.support_mask_hash,
                "support_index": arm.artifact_provenance.get("support_index"),
            }
        )
        if arm.support_identity_hash != expected_support_identity:
            raise FactorialReportError(f"arm {arm.arm} support identity mismatch")
        if arm.nature_stream_hash != arm.environment_stream_hash:
            raise FactorialReportError(f"arm {arm.arm} nature/environment stream mismatch")
        if canonical_hash(nature_trace(arm.episode)) != arm.nature_trace_hash:
            raise FactorialReportError(f"arm {arm.arm} realized nature trace hash mismatch")
        if canonical_hash(arm.episode) != arm.episode_hash:
            raise FactorialReportError(f"arm {arm.arm} episode hash mismatch")
        if not math.isfinite(arm.candidate_payoff) or not math.isfinite(arm.opponent_payoff):
            raise FactorialReportError(f"arm {arm.arm} payoff is nonfinite")
        if arm.candidate_payoff != float(arm.episode.candidate_payoff):
            raise FactorialReportError(f"arm {arm.arm} candidate payoff mismatch")
        if arm.opponent_payoff != float(arm.episode.opponent_payoff):
            raise FactorialReportError(f"arm {arm.arm} opponent payoff mismatch")
        if canonical_hash(arm.episode.opponent_spec) != canonical_hash(
            _expected_episode_opponent_spec(arm.episode.scenario)
        ):
            raise FactorialReportError(f"arm {arm.arm} episode opponent differs from scenario")
        _validate_capability_manifest(
            arm,
            arm.episode.scenario.scenario_id,
            contract.master_seed,
        )
    scenario_hashes = _scenario_hashes(arms[0].episode.scenario)
    for field, expected in scenario_hashes.items():
        if getattr(arms[0], field) != expected:
            raise FactorialReportError(f"row {row.key} {field} does not match scenario")
    scenario = arms[0].episode.scenario
    scenario_payloads = {canonical_hash(arm.episode.scenario) for arm in arms}
    if len(scenario_payloads) != 1 or canonical_hash(scenario) != row.scenario_hash:
        raise FactorialReportError(f"row {row.key} scenario bytes differ across arms")
    if row.family != scenario.game_family or row.candidate_role != scenario.candidate_role:
        raise FactorialReportError(f"row {row.key} family/role differs from scenario")
    allowed_roles = FAMILY_ROLES.get(row.family)
    if allowed_roles is None or scenario.candidate_role not in allowed_roles:
        raise FactorialReportError(f"row {row.key} uses an invalid family role")
    expected_opponent_role = allowed_roles[1] if scenario.candidate_role == allowed_roles[0] else allowed_roles[0]
    if scenario.opponent_role != expected_opponent_role:
        raise FactorialReportError(f"row {row.key} candidate/opponent roles are not complementary")
    expected_key = f"{row.family}:{scenario.scenario_id}:{row.candidate_role}"
    if row.key != expected_key:
        raise FactorialReportError(f"row key mismatch: expected {expected_key}, found {row.key}")
    randomness = scenario.metadata.get("factorial_randomness")
    if not isinstance(randomness, dict) or randomness.get("master_seed_hash") != contract.master_seed_hash:
        raise FactorialReportError(f"row {row.key} master-seed provenance mismatch")
    expected_environment_seed = factorial_named_seed(
        contract.master_seed, scenario.scenario_id, "environment"
    )
    expected_opponent_seed = factorial_named_seed(
        contract.master_seed, scenario.scenario_id, "opponent-policy"
    )
    expected_environment_hash = factorial_stream_hash(
        scenario.scenario_id, "environment", expected_environment_seed
    )
    expected_opponent_hash = factorial_stream_hash(
        scenario.scenario_id, "opponent-policy", expected_opponent_seed
    )
    expected_economic_seed = factorial_named_seed(
        contract.master_seed, scenario.scenario_id, "candidate-economic"
    )
    expected_economic_hash = factorial_stream_hash(
        scenario.scenario_id, "candidate-economic", expected_economic_seed
    )
    if int(scenario.seed) != expected_environment_seed:
        raise FactorialReportError(f"row {row.key} environment seed differs from frozen derivation")
    if int(scenario.opponent_spec.get("seed", -1)) != expected_opponent_seed:
        raise FactorialReportError(f"row {row.key} opponent seed differs from frozen derivation")
    if any(arm.environment_stream_hash != expected_environment_hash for arm in arms):
        raise FactorialReportError(f"row {row.key} environment stream hash is forged")
    if any(arm.opponent_stream_hash != expected_opponent_hash for arm in arms):
        raise FactorialReportError(f"row {row.key} opponent stream hash is forged")
    if any(arm.economic_stream_hash != expected_economic_hash for arm in arms):
        raise FactorialReportError(f"row {row.key} economic stream hash is forged")
    expected_randomness_fields = {
        "schema": "glee.factorial.stream_manifest.v2",
        "master_seed_hash": contract.master_seed_hash,
        "scenario_seed_hash": str(randomness.get("scenario_seed_hash") or ""),
        "environment_seed_hash": expected_environment_hash,
        "opponent_seed_hash": expected_opponent_hash,
    }
    if randomness != expected_randomness_fields or not _is_sha256(
        expected_randomness_fields["scenario_seed_hash"]
    ):
        raise FactorialReportError(f"row {row.key} environment/opponent manifest is forged")
    claims_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for arm in arms:
        for owner, claim in arm.randomness_audit["claims"].items():
            claims_by_owner[owner].append(claim)
    if len({_expected_rng_seed_hash(contract.master_seed, scenario.scenario_id, owner) for owner in claims_by_owner}) != len(claims_by_owner):
        raise FactorialReportError(f"row {row.key} candidate RNG owners alias a seed")
    for owner, claims in claims_by_owner.items():
        if len({canonical_hash(claim) for claim in claims}) != 1:
            raise FactorialReportError(f"row {row.key} arm-dependent {owner} RNG trace")
    return {
        "row": row,
        "scenario": scenario,
        "scenario_id": scenario.scenario_id,
        "config_id": scenario.config_id,
        "eligibility": eligibility,
        "digest": _row_digest(row),
        "contrasts": row.contrasts(),
    }


def _simple_estimate(values: Sequence[float], alpha: float, minimum: int) -> dict[str, Any]:
    n = len(values)
    if n < minimum:
        return {
            "reportable": False,
            "n": n,
            "reason": f"requires_at_least_{minimum}_paired_rows",
        }
    point = mean(values)
    sample_variance = variance(values) if n > 1 else 0.0
    se = math.sqrt(sample_variance / n)
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    return {
        "reportable": True,
        "n": n,
        "effect": point,
        "standard_error": se,
        "confidence_level": 1.0 - alpha,
        "confidence_interval": [point - z * se, point + z * se],
        "sample_variance": sample_variance,
    }


def _equal_family_estimate(
    records: Sequence[dict[str, Any]],
    contrast: str,
    alpha: float,
    minimum: int,
) -> dict[str, Any]:
    by_family: dict[str, list[float]] = defaultdict(list)
    for record in records:
        by_family[record["row"].family].append(float(record["contrasts"][contrast]))
    if not by_family:
        return {"reportable": False, "n": 0, "reason": "empty_population"}
    family_rows = {
        family: _simple_estimate(values, alpha, minimum)
        for family, values in sorted(by_family.items())
    }
    failed = [family for family, row in family_rows.items() if not row["reportable"]]
    if failed:
        return {
            "reportable": False,
            "n": sum(len(values) for values in by_family.values()),
            "reason": "underpowered_family_cells",
            "failed_families": failed,
            "families": family_rows,
        }
    family_count = len(family_rows)
    point = mean(float(row["effect"]) for row in family_rows.values())
    se = math.sqrt(
        sum(float(row["standard_error"]) ** 2 for row in family_rows.values())
    ) / family_count
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    return {
        "reportable": True,
        "n": sum(len(values) for values in by_family.values()),
        "family_count": family_count,
        "family_weighting": "equal_over_nonempty_structurally_eligible_families",
        "effect": point,
        "standard_error": se,
        "confidence_level": 1.0 - alpha,
        "confidence_interval": [point - z * se, point + z * se],
        "families": family_rows,
    }


def _population(records: Sequence[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    if name == "overall":
        return list(records)
    return [record for record in records if record["eligibility"][name]]


def _group_summaries(
    records: Sequence[dict[str, Any]],
    contrast: str,
    alpha: float,
    minimum: int,
) -> dict[str, Any]:
    groupers = {
        "family": lambda record: record["row"].family,
        "family_role": lambda record: f'{record["row"].family}:{record["row"].candidate_role}',
        "family_configuration": lambda record: f'{record["row"].family}:{record["config_id"]}',
    }
    output: dict[str, Any] = {}
    for name, key_fn in groupers.items():
        groups: dict[str, list[float]] = defaultdict(list)
        for record in records:
            groups[key_fn(record)].append(float(record["contrasts"][contrast]))
        output[name] = {
            key: _simple_estimate(values, alpha, minimum)
            for key, values in sorted(groups.items())
        }
    return output


def _normal_pvalue(effect: float, se: float) -> float:
    if se == 0.0:
        return 1.0 if effect == 0.0 else 0.0
    return min(1.0, 2.0 * (1.0 - NormalDist().cdf(abs(effect / se))))


def _holm(primary: list[dict[str, Any]], alpha: float) -> dict[str, Any]:
    if len(primary) != 3 or any(not row["estimate"].get("reportable") for row in primary):
        return {
            "reportable": False,
            "reason": "all_three_primary_estimands_must_be_reportable",
            "hypotheses": primary,
        }
    ordered = sorted(primary, key=lambda row: (row["unadjusted_p"], row["name"]))
    running_adjusted = 0.0
    m = len(ordered)
    for rank, row in enumerate(ordered, start=1):
        multiplier = m - rank + 1
        adjusted = min(1.0, multiplier * row["unadjusted_p"])
        running_adjusted = max(running_adjusted, adjusted)
        row["holm_rank"] = rank
        row["holm_multiplier"] = multiplier
        row["holm_adjusted_p"] = running_adjusted
        adjusted_alpha = alpha / multiplier
        estimate = row["estimate"]
        z = NormalDist().inv_cdf(1.0 - adjusted_alpha / 2.0)
        effect = float(estimate["effect"])
        se = float(estimate["standard_error"])
        interval = [effect - z * se, effect + z * se]
        row["holm_adjusted_alpha"] = adjusted_alpha
        row["holm_adjusted_confidence_interval"] = interval
        if interval[0] > 0.0 and running_adjusted < alpha:
            row["decision"] = "improvement"
        elif interval[1] < 0.0 and running_adjusted < alpha:
            row["decision"] = "harm"
        else:
            row["decision"] = "nonconfirming"
    return {
        "reportable": True,
        "alpha": alpha,
        "method": "holm_step_down_two_sided_normal_p",
        "hypotheses": sorted(ordered, key=lambda row: row["name"]),
    }


def build_factorial_report(
    rows: Sequence[FactorialRow],
    contract: FactorialReportContract | None = None,
) -> dict[str, Any]:
    contract = contract or FactorialReportContract()
    model_c: Mapping[str, Any] | None = None
    receiver: Mapping[str, Any] | None = None
    if contract.is_production:
        contract.validate_production_freeze()
        if not rows:
            raise FactorialReportError("production report cannot verify an empty arm set")
        first_arms = sorted(rows[0].arms, key=lambda item: item.arm)
        if not first_arms:
            raise FactorialReportError("production report lacks artifact provenance")
        provenance = first_arms[0].artifact_provenance
        if canonical_hash(provenance) != contract.required_artifact_provenance_hash:
            raise FactorialReportError("production report uses the wrong frozen artifact manifest")
        model_c = _verified_artifact_json(provenance, "response_model")
        _verified_artifact_json(provenance, "support_index")
        receiver = _receiver_contract(provenance)
    elif contract.schema != SYNTHETIC_CONTRACT_SCHEMA:
        raise FactorialReportError("unknown report contract schema")
    if len(rows) != contract.expected_rows:
        raise FactorialReportError(
            f"expected {contract.expected_rows} paired rows, found {len(rows)}"
        )
    records = [
        _validate_row(row, contract, model_c=model_c, receiver_contract=receiver)
        for row in rows
    ]
    keys = [record["row"].key for record in records]
    scenario_ids = [record["scenario_id"] for record in records]
    if len(set(keys)) != len(keys) or len(set(scenario_ids)) != len(scenario_ids):
        raise FactorialReportError("duplicate paired scenario/key")
    family_counts = Counter(record["row"].family for record in records)
    if dict(sorted(family_counts.items())) != dict(sorted(contract.family_counts.items())):
        raise FactorialReportError(
            f"family counts mismatch: expected {contract.family_counts}, found {dict(family_counts)}"
        )
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        role_counts[record["row"].family][record["row"].candidate_role] += 1
    for family, counts in role_counts.items():
        if set(counts) != set(FAMILY_ROLES[family]) or max(counts.values()) - min(counts.values()) > 0:
            raise FactorialReportError(f"candidate roles are not exactly balanced in {family}")
    records = sorted(records, key=lambda record: record["row"].key)
    preoutcome_manifest = [_preoutcome_manifest_record(record) for record in records]
    preoutcome_manifest_sha256 = canonical_hash(preoutcome_manifest)
    if contract.is_production and preoutcome_manifest_sha256 != contract.scenario_manifest_sha256:
        raise FactorialReportError("paired rows differ from the frozen pre-outcome scenario manifest")
    estimands: dict[str, dict[str, Any]] = {}
    for population in ("overall", *ELIGIBILITY_FIELDS):
        population_records = _population(records, population)
        estimands[population] = {
            contrast: _equal_family_estimate(
                population_records,
                contrast,
                contract.alpha,
                contract.minimum_cell_rows,
            )
            for contrast in CONTRASTS
        }
    summaries = {
        contrast: _group_summaries(
            records, contrast, contract.alpha, contract.minimum_cell_rows
        )
        for contrast in CONTRASTS
    }
    primary: list[dict[str, Any]] = []
    for name, population, contrast in PRIMARY_HYPOTHESES:
        estimate = estimands[population][contrast]
        row = {"name": name, "population": population, "contrast": contrast, "estimate": estimate}
        if estimate.get("reportable"):
            row["unadjusted_p"] = _normal_pvalue(
                float(estimate["effect"]), float(estimate["standard_error"])
            )
        else:
            row["unadjusted_p"] = None
        primary.append(row)
    eligibility_counts = {
        family: {
            field: sum(
                int(record["eligibility"][field])
                for record in records
                if record["row"].family == family
            )
            for field in ELIGIBILITY_FIELDS
        }
        for family in sorted(contract.family_counts)
    }
    artifact_hash = _same_hash(
        (record["row"].arms[0].artifact_provenance_hash for record in records),
        "artifact_provenance_hash across scenarios",
    )
    row_digests = [record["digest"] for record in records]
    report: dict[str, Any] = {
        "schema": "glee.research.factorial_report.v1",
        "contract": contract.to_dict(),
        "contract_sha256": canonical_hash(contract.to_dict()),
        "paired_rows": len(records),
        "arm_episodes": 4 * len(records),
        "family_counts": dict(sorted(family_counts.items())),
        "role_counts": {
            family: dict(sorted(counts.items())) for family, counts in sorted(role_counts.items())
        },
        "eligibility_counts": eligibility_counts,
        "artifact_provenance_hash": artifact_hash,
        "input_hashes": {
            "preoutcome_scenario_manifest_sha256": preoutcome_manifest_sha256,
            "row_digest_root_sha256": canonical_hash(row_digests),
            "sorted_row_digests_sha256": canonical_hash(sorted(row_digests)),
            "research_question_sha256": contract.research_question_sha256,
        },
        "estimands": estimands,
        "summaries": summaries,
        "holm": _holm(primary, contract.alpha),
        "boundaries": {
            "payoff_study_executed_by_this_module": False,
            "eligibility_is_pre_outcome_scenario_metadata": contract.is_production,
            "production_evidence": contract.is_production,
            "arm_order_invariant": True,
            "paired_scenario_is_inference_unit": True,
        },
    }
    report["output_sha256"] = canonical_hash(report)
    return report


def validate_factorial_report(
    rows: Sequence[FactorialRow],
    report: Mapping[str, Any],
    contract: FactorialReportContract | None = None,
) -> dict[str, Any]:
    contract = contract or FactorialReportContract()
    contract.validate_production_freeze()
    expected = build_factorial_report(rows, contract)
    observed = to_jsonable(report)
    if canonical_hash(observed) != canonical_hash(expected) or observed != expected:
        raise FactorialReportError("factorial report does not reconstruct from paired rows")
    if canonical_hash({key: value for key, value in observed.items() if key != "output_sha256"}) != observed.get(
        "output_sha256"
    ):
        raise FactorialReportError("factorial report output hash mismatch")
    return {
        "schema": PRODUCTION_VALIDATION_SCHEMA,
        "passed": True,
        "evidence_class": "production_frozen_contract",
        "paired_rows": len(rows),
        "input_hashes": expected["input_hashes"],
        "output_sha256": expected["output_sha256"],
        "contract_sha256": expected["contract_sha256"],
    }


def validate_synthetic_factorial_report(
    rows: Sequence[FactorialRow],
    report: Mapping[str, Any],
    contract: FactorialReportContract,
) -> dict[str, Any]:
    """Validate bounded arithmetic fixtures without conferring production status."""

    if contract.schema != SYNTHETIC_CONTRACT_SCHEMA:
        raise FactorialReportError("synthetic validation requires a synthetic contract")
    expected = build_factorial_report(rows, contract)
    observed = to_jsonable(report)
    if canonical_hash(observed) != canonical_hash(expected) or observed != expected:
        raise FactorialReportError("synthetic factorial report does not reconstruct")
    return {
        "schema": SYNTHETIC_VALIDATION_SCHEMA,
        "passed": True,
        "evidence_class": "synthetic_arithmetic_only_not_production",
        "paired_rows": len(rows),
        "input_hashes": expected["input_hashes"],
        "output_sha256": expected["output_sha256"],
        "contract_sha256": expected["contract_sha256"],
    }
