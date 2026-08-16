"""Fail-closed pre-outcome manifest infrastructure for the future 2x2 study.

The module never runs an episode.  It binds immutable scenario inputs and the
future receiver/evaluator contract before any treatment action or payoff exists.
Reduced manifests are explicitly synthetic infrastructure evidence.  Production
status additionally requires the separately audited authorization pin in
``factorial_report``; Wave 5A deliberately leaves that pin unset.
"""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from glee_eval.data.schemas import Scenario, to_jsonable
from glee_eval.experiments import factorial_report
from glee_eval.experiments.factorial import (
    FACTORIAL_ARMS,
    FAMILY_ROLES,
    factorial_named_seed,
    factorial_scenario_seed,
    factorial_stream_hash,
)
from glee_eval.experiments.factorial_report import (
    ELIGIBILITY_DERIVATION_SPEC,
    FROZEN_ALPHA,
    FROZEN_EXPECTED_ROWS,
    FROZEN_FAMILY_COUNTS,
    FROZEN_MASTER_SEED,
    canonical_hash,
    derive_factorial_eligibility,
)


PRODUCTION_SCHEMA = "glee.research.preoutcome_manifest.production.v1"
SYNTHETIC_SCHEMA = "glee.research.preoutcome_manifest.synthetic.v1"
ROW_SCHEMA = "glee.research.preoutcome_manifest_row.v1"
OUTCOME_ADMISSION_SCHEMA = "glee.research.factorial_outcome_admission.v1"
SYNTHETIC_EVIDENCE_CLASS = "infrastructure_only_non_evidence"
# Separate from the report-contract pin because the manifest contract contains
# receiver/design/dependency bytes that a report hash alone cannot reconstruct.
AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256: str | None = None
FORBIDDEN_PREOUTCOME_KEYS = frozenset(
    {
        "candidate_payoff",
        "opponent_payoff",
        "terminal_outcome",
        "outcome",
        "treatment_action",
        "receiver_output",
        "included_after_outcome",
    }
)
ARM_ENTRYPOINT_KEYS = {
    "e0_l0": "research.CANDIDATES.wave3_factorial_agents:Factorial00Agent",
    "e0_l1": "research.CANDIDATES.wave3_factorial_agents:Factorial01Agent",
    "e1_l0": "research.CANDIDATES.wave3_factorial_agents:Factorial10Agent",
    "e1_l1": "research.CANDIDATES.wave3_factorial_agents:Factorial11Agent",
}
NAMED_STREAMS = (
    "scenario",
    "environment",
    "opponent-policy",
    "candidate-economic",
    "candidate-eprocess",
    "candidate-language",
    "controlled-receiver",
    "factorial-evaluator",
)
REQUIRED_DEPENDENCY_HASHES = frozenset(
    {"factorial_evaluator", "factorial_report", "eligibility_derivation"}
)


class PreOutcomeManifestError(RuntimeError):
    """Raised before production evidence when the frozen manifest is invalid."""


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _assert_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PreOutcomeManifestError(f"{label} fields differ from the frozen schema")


def _assert_no_forbidden(value: Any, path: str = "manifest") -> None:
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden(child, f"{path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    overlap = FORBIDDEN_PREOUTCOME_KEYS.intersection(value)
    if overlap:
        raise PreOutcomeManifestError(
            f"pre-outcome manifest contains post-treatment fields at {path}: {sorted(overlap)}"
        )
    for key, child in value.items():
        _assert_no_forbidden(child, f"{path}.{key}")


@dataclass(frozen=True)
class PreOutcomeManifestContract:
    schema: str
    expected_rows: int
    expected_family_counts: tuple[tuple[str, int], ...]
    master_seed: int
    alpha: float
    scenario_design_id: str
    scenario_design_sha256: str
    model_c_payload_sha256: str
    support_masks_sha256: str
    receiver_contract: Mapping[str, Any]
    receiver_contract_sha256: str
    artifact_provenance: Mapping[str, Any]
    artifact_provenance_sha256: str
    opponent_population_sha256: str
    config_catalogue_sha256: str
    dependency_sha256: Mapping[str, str]
    agent_entrypoints: Mapping[str, str]
    eprocess_contract: Mapping[str, Any]
    language_policy_contract: Mapping[str, Any]
    estimand_contract: Mapping[str, Any]
    missingness_policy: Mapping[str, Any]
    retry_failure_policy: Mapping[str, Any]
    report_schema: str
    report_contract_sha256: str

    @property
    def family_counts(self) -> dict[str, int]:
        return dict(self.expected_family_counts)

    @property
    def is_production(self) -> bool:
        return self.schema == PRODUCTION_SCHEMA

    @classmethod
    def synthetic(
        cls,
        *,
        rows_per_family: int,
        receiver_contract: Mapping[str, Any],
        artifact_provenance: Mapping[str, Any],
        scenario_design_sha256: str,
        model_c_payload_sha256: str,
        support_masks_sha256: str,
        master_seed: int = FROZEN_MASTER_SEED,
    ) -> "PreOutcomeManifestContract":
        fake_hashes = {
            "factorial_evaluator": "1" * 64,
            "factorial_report": "2" * 64,
            "eligibility_derivation": canonical_hash(ELIGIBILITY_DERIVATION_SPEC),
        }
        return cls(
            schema=SYNTHETIC_SCHEMA,
            expected_rows=int(rows_per_family) * len(FROZEN_FAMILY_COUNTS),
            expected_family_counts=tuple(
                (family, int(rows_per_family)) for family, _ in FROZEN_FAMILY_COUNTS
            ),
            master_seed=int(master_seed),
            alpha=FROZEN_ALPHA,
            scenario_design_id="synthetic_fixture_only",
            scenario_design_sha256=str(scenario_design_sha256),
            model_c_payload_sha256=str(model_c_payload_sha256),
            support_masks_sha256=str(support_masks_sha256),
            receiver_contract=copy.deepcopy(receiver_contract),
            receiver_contract_sha256=canonical_hash(receiver_contract),
            artifact_provenance=copy.deepcopy(artifact_provenance),
            artifact_provenance_sha256=canonical_hash(artifact_provenance),
            opponent_population_sha256="4" * 64,
            config_catalogue_sha256="5" * 64,
            dependency_sha256=fake_hashes,
            agent_entrypoints=dict(ARM_ENTRYPOINT_KEYS),
            eprocess_contract={
                "schema": "glee.eprocess.reference_obedience.v1",
                "threshold": 20.0,
                "treatment_label": "model-relative e-process against a fixed hash-locked Model-C reference",
            },
            language_policy_contract={
                "schema": "glee.language.persuasion_templates.v1",
                "receiver_contract_sha256": canonical_hash(receiver_contract),
            },
            estimand_contract={
                "schema": "glee.research.wave4_estimands.v2",
                "primary": ["eprocess_eligible:E", "language_eligible:L", "joint_eligible:I"],
                "secondary": "equal_family_overall",
                "holm_family": ["E", "L", "I"],
                "alpha": FROZEN_ALPHA,
            },
            missingness_policy={
                "schema": "glee.research.missingness.intent_to_treat.v1",
                "exclude_after_assignment": False,
                "receiver_failures": "included_and_labelled",
                "malformed_outputs": "included_and_labelled",
            },
            retry_failure_policy={
                "schema": "glee.research.receiver_failure.v1",
                "retries": 0,
                "timeout_seconds": 30,
                "refusal": "included_failure",
                "malformed": "included_failure",
                "missing": "included_failure",
            },
            report_schema="glee.research.factorial_report.v1",
            report_contract_sha256="6" * 64,
        )

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    def validate(self, *, require_production: bool) -> None:
        if self.schema not in {PRODUCTION_SCHEMA, SYNTHETIC_SCHEMA}:
            raise PreOutcomeManifestError("unknown pre-outcome contract schema")
        if require_production:
            if self.schema != PRODUCTION_SCHEMA:
                raise PreOutcomeManifestError("production validation rejects synthetic contracts")
            if factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256 is None:
                raise PreOutcomeManifestError(
                    "production manifest is unauthorized while AUTHORIZED_PRODUCTION_CONTRACT_SHA256 is None"
                )
            if AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256 is None:
                raise PreOutcomeManifestError(
                    "production manifest contract is not independently hash-authorized"
                )
            if canonical_hash(self.to_dict()) != AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256:
                raise PreOutcomeManifestError("pre-outcome manifest contract hash is unauthorized")
            if (
                self.expected_rows != FROZEN_EXPECTED_ROWS
                or self.expected_family_counts != FROZEN_FAMILY_COUNTS
                or self.master_seed != FROZEN_MASTER_SEED
                or self.alpha != FROZEN_ALPHA
            ):
                raise PreOutcomeManifestError("production manifest changed frozen size/seed/alpha")
            if self.report_contract_sha256 != factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256:
                raise PreOutcomeManifestError("manifest is not bound to the authorized report contract")
        required_hashes = {
            "scenario_design": self.scenario_design_sha256,
            "model_c_payload": self.model_c_payload_sha256,
            "support_masks": self.support_masks_sha256,
            "receiver_contract": self.receiver_contract_sha256,
            "artifact_provenance": self.artifact_provenance_sha256,
            "opponent_population": self.opponent_population_sha256,
            "config_catalogue": self.config_catalogue_sha256,
            "report_contract": self.report_contract_sha256,
            **dict(self.dependency_sha256),
        }
        bad = [name for name, value in required_hashes.items() if not _is_sha256(value)]
        if bad:
            raise PreOutcomeManifestError(f"manifest contract has invalid hashes: {bad}")
        if canonical_hash(self.receiver_contract) != self.receiver_contract_sha256:
            raise PreOutcomeManifestError("receiver contract hash mismatch")
        if canonical_hash(self.artifact_provenance) != self.artifact_provenance_sha256:
            raise PreOutcomeManifestError("artifact provenance hash mismatch")
        if self.artifact_provenance.get("receiver_contract") != to_jsonable(
            self.receiver_contract
        ):
            raise PreOutcomeManifestError(
                "artifact provenance embeds another receiver contract"
            )
        if set(self.dependency_sha256) != set(REQUIRED_DEPENDENCY_HASHES):
            raise PreOutcomeManifestError("dependency hashes differ from the required source set")
        output_contract = self.receiver_contract.get("output_contract")
        if not isinstance(output_contract, Mapping):
            raise PreOutcomeManifestError("receiver contract lacks a frozen output contract")
        if not isinstance(output_contract.get("schema"), Mapping):
            raise PreOutcomeManifestError("receiver output schema is not frozen")
        if not str(output_contract.get("decision_field") or ""):
            raise PreOutcomeManifestError("receiver decision field is not frozen")
        if dict(self.agent_entrypoints) != ARM_ENTRYPOINT_KEYS:
            raise PreOutcomeManifestError("agent entrypoints differ from the four forced arms")
        if self.eprocess_contract.get("threshold") != 20.0:
            raise PreOutcomeManifestError("e-process threshold differs from 20")
        if self.language_policy_contract.get("receiver_contract_sha256") != self.receiver_contract_sha256:
            raise PreOutcomeManifestError("language policy is bound to another receiver contract")
        if self.missingness_policy.get("exclude_after_assignment") is not False:
            raise PreOutcomeManifestError("post-treatment exclusion is forbidden")


def scenario_design_sha256(scenarios: Sequence[Scenario]) -> str:
    """Hash the exact pre-outcome scenario identities and immutable payloads."""

    family_indices: dict[str, int] = defaultdict(int)
    indexed: list[tuple[Scenario, int]] = []
    for scenario in scenarios:
        family_index = family_indices[scenario.game_family]
        family_indices[scenario.game_family] += 1
        indexed.append((scenario, family_index))
    return _indexed_scenario_design_sha256(indexed)


def _indexed_scenario_design_sha256(
    indexed: Sequence[tuple[Scenario, int]],
) -> str:
    records = [
        {
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": canonical_hash(scenario),
            "configuration_sha256": canonical_hash(
                {
                    "config_id": scenario.config_id,
                    "public_parameters": scenario.public_parameters,
                }
            ),
            "family": scenario.game_family,
            "family_index": family_index,
            "candidate_role": scenario.candidate_role,
            "opponent_role": scenario.opponent_role,
            "source": scenario.source,
        }
        for scenario, family_index in indexed
    ]
    records.sort(key=lambda record: (record["family"], record["scenario_id"], record["candidate_role"]))
    return canonical_hash(records)


def support_masks_sha256(
    support_masks: Mapping[str, Mapping[str, Any]],
) -> str:
    """Hash the exact scenario-to-support mapping before assignment."""

    return canonical_hash(
        [
            {"scenario_id": scenario_id, "support_mask": to_jsonable(support_masks[scenario_id])}
            for scenario_id in sorted(support_masks)
        ]
    )


def _horizon(scenario: Scenario) -> int:
    value = scenario.public_parameters.get(
        "total_rounds", scenario.public_parameters.get("max_rounds", 0)
    )
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stream_manifest(
    contract: PreOutcomeManifestContract,
    scenario: Scenario,
    *,
    family_index: int,
) -> dict[str, str]:
    output: dict[str, str] = {}
    for stream in NAMED_STREAMS:
        if stream == "scenario":
            randomness = scenario.metadata.get("factorial_randomness")
            if not isinstance(randomness, Mapping):
                raise PreOutcomeManifestError("scenario RNG provenance is missing")
            expected_keys = {
                "schema",
                "master_seed_hash",
                "scenario_seed_hash",
                "environment_seed_hash",
                "opponent_seed_hash",
            }
            _assert_exact_keys(randomness, expected_keys, "scenario RNG provenance")
            if randomness.get("schema") != "glee.factorial.stream_manifest.v2":
                raise PreOutcomeManifestError("scenario RNG provenance schema changed")
            if randomness.get("master_seed_hash") != canonical_hash(
                {"master_seed": contract.master_seed}
            ):
                raise PreOutcomeManifestError("scenario master-seed provenance changed")
            scenario_seed = factorial_scenario_seed(
                contract.master_seed, scenario.game_family, family_index
            )
            scenario_hash = factorial_stream_hash(
                scenario.scenario_id, "scenario", scenario_seed
            )
            if randomness.get("scenario_seed_hash") != scenario_hash:
                raise PreOutcomeManifestError("scenario stream provenance changed")
            output[stream] = scenario_hash
            continue
        seed = factorial_named_seed(contract.master_seed, scenario.scenario_id, stream)
        output[stream] = factorial_stream_hash(scenario.scenario_id, stream, seed)
    randomness = scenario.metadata["factorial_randomness"]
    if randomness.get("environment_seed_hash") != output["environment"]:
        raise PreOutcomeManifestError("scenario environment-stream provenance changed")
    if randomness.get("opponent_seed_hash") != output["opponent-policy"]:
        raise PreOutcomeManifestError("scenario opponent-stream provenance changed")
    if len(set(output.values())) != len(output):
        raise PreOutcomeManifestError("named RNG streams alias")
    return output


def _row_for_scenario(
    scenario: Scenario,
    *,
    contract: PreOutcomeManifestContract,
    model_c: Mapping[str, Any],
    support_mask: Mapping[str, Any],
    family_index: int,
) -> dict[str, Any]:
    allowed = FAMILY_ROLES.get(scenario.game_family)
    if allowed is None or scenario.candidate_role not in allowed:
        raise PreOutcomeManifestError("scenario uses an invalid candidate role")
    opponent = allowed[1] if scenario.candidate_role == allowed[0] else allowed[0]
    if scenario.opponent_role != opponent:
        raise PreOutcomeManifestError("scenario roles are not complementary")
    eligibility = derive_factorial_eligibility(
        scenario,
        model_c=model_c,
        receiver_contract=contract.receiver_contract,
    )
    streams = _stream_manifest(contract, scenario, family_index=family_index)
    expected_environment_seed = factorial_named_seed(
        contract.master_seed, scenario.scenario_id, "environment"
    )
    expected_opponent_seed = factorial_named_seed(
        contract.master_seed, scenario.scenario_id, "opponent-policy"
    )
    if int(scenario.seed) != expected_environment_seed:
        raise PreOutcomeManifestError("scenario environment seed is not the frozen named seed")
    if int(scenario.opponent_spec.get("seed", -1)) != expected_opponent_seed:
        raise PreOutcomeManifestError("scenario opponent seed is not the frozen named seed")
    row: dict[str, Any] = {
        "schema": ROW_SCHEMA,
        "row_key": f"{scenario.game_family}:{scenario.scenario_id}:{scenario.candidate_role}",
        "scenario_id": scenario.scenario_id,
        "scenario": to_jsonable(scenario),
        "scenario_hash": canonical_hash(scenario),
        "configuration_id": scenario.config_id,
        "configuration_hash": canonical_hash(
            {"config_id": scenario.config_id, "public_parameters": scenario.public_parameters}
        ),
        "family": scenario.game_family,
        "family_index": family_index,
        "candidate_role": scenario.candidate_role,
        "opponent_role": scenario.opponent_role,
        "horizon": _horizon(scenario),
        "public_state": copy.deepcopy(scenario.public_parameters),
        "public_state_hash": canonical_hash(scenario.public_parameters),
        "source": scenario.source,
        "eligibility": eligibility,
        "eligibility_hash": canonical_hash(eligibility),
        "support_mask": copy.deepcopy(support_mask),
        "support_mask_hash": canonical_hash(support_mask),
        "receiver_contract_sha256": contract.receiver_contract_sha256,
        "rng_stream_sha256": streams,
        "arm_rng_stream_sha256": {
            arm: {
                "environment": streams["environment"],
                "economic": streams["candidate-economic"],
                "receiver": streams["controlled-receiver"],
                "evaluator": streams["factorial-evaluator"],
            }
            for arm in FACTORIAL_ARMS
        },
        "agent_entrypoints": dict(contract.agent_entrypoints),
        "artifact_provenance_sha256": contract.artifact_provenance_sha256,
        "dependency_sha256": dict(contract.dependency_sha256),
        "language_policy": copy.deepcopy(contract.language_policy_contract),
        "eprocess_contract": copy.deepcopy(contract.eprocess_contract),
        "retry_failure_policy": copy.deepcopy(contract.retry_failure_policy),
        "missingness_policy": copy.deepcopy(contract.missingness_policy),
    }
    _assert_no_forbidden(row)
    row["row_sha256"] = canonical_hash(row)
    return row


def build_preoutcome_manifest(
    scenarios: Sequence[Scenario],
    *,
    contract: PreOutcomeManifestContract,
    model_c: Mapping[str, Any],
    support_masks: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a pre-arm manifest; no episode runner or payoff surface is called."""

    contract.validate(require_production=contract.is_production)
    if len(scenarios) != contract.expected_rows:
        raise PreOutcomeManifestError(
            f"expected {contract.expected_rows} scenarios, found {len(scenarios)}"
        )
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise PreOutcomeManifestError("duplicate scenario id")
    if set(support_masks) != set(scenario_ids):
        raise PreOutcomeManifestError("support masks do not cover the exact scenario manifest")
    if scenario_design_sha256(scenarios) != contract.scenario_design_sha256:
        raise PreOutcomeManifestError("scenario design differs from the frozen contract")
    if canonical_hash(model_c) != contract.model_c_payload_sha256:
        raise PreOutcomeManifestError("Model-C payload differs from the frozen contract")
    if support_masks_sha256(support_masks) != contract.support_masks_sha256:
        raise PreOutcomeManifestError("support masks differ from the frozen contract")
    family_indices: dict[str, int] = defaultdict(int)
    rows = []
    for scenario in scenarios:
        family_index = family_indices[scenario.game_family]
        family_indices[scenario.game_family] += 1
        rows.append(
            _row_for_scenario(
                scenario,
                contract=contract,
                model_c=model_c,
                support_mask=support_masks[scenario.scenario_id],
                family_index=family_index,
            )
        )
    family_counts = Counter(row["family"] for row in rows)
    if dict(sorted(family_counts.items())) != dict(sorted(contract.family_counts.items())):
        raise PreOutcomeManifestError("family counts differ from the contract")
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        role_counts[row["family"]][row["candidate_role"]] += 1
    for family, counts in role_counts.items():
        if set(counts) != set(FAMILY_ROLES[family]) or len(set(counts.values())) != 1:
            raise PreOutcomeManifestError(f"roles are not exactly balanced in {family}")
    rows.sort(key=lambda row: row["row_key"])
    manifest: dict[str, Any] = {
        "schema": contract.schema,
        "evidence_class": (
            "production_preoutcome_manifest"
            if contract.is_production
            else SYNTHETIC_EVIDENCE_CLASS
        ),
        "contract": contract.to_dict(),
        "contract_sha256": canonical_hash(contract.to_dict()),
        "row_count": len(rows),
        "arm_count": len(rows) * len(FACTORIAL_ARMS),
        "family_counts": dict(sorted(family_counts.items())),
        "role_counts": {
            family: dict(sorted(counts.items())) for family, counts in sorted(role_counts.items())
        },
        "rows": rows,
        "row_root_sha256": canonical_hash([row["row_sha256"] for row in rows]),
        "estimand_contract": copy.deepcopy(contract.estimand_contract),
        "report_schema": contract.report_schema,
        "outcomes_present": False,
    }
    _assert_no_forbidden(manifest)
    manifest["manifest_sha256"] = canonical_hash(manifest)
    return manifest


def _validate_manifest_common(
    manifest: Mapping[str, Any],
    *,
    contract: PreOutcomeManifestContract,
    model_c: Mapping[str, Any],
    require_production: bool,
) -> None:
    contract.validate(require_production=require_production)
    observed = to_jsonable(manifest)
    _assert_no_forbidden(observed)
    _assert_exact_keys(
        observed,
        {
            "schema",
            "evidence_class",
            "contract",
            "contract_sha256",
            "row_count",
            "arm_count",
            "family_counts",
            "role_counts",
            "rows",
            "row_root_sha256",
            "estimand_contract",
            "report_schema",
            "outcomes_present",
            "manifest_sha256",
        },
        "manifest",
    )
    if observed.get("contract") != contract.to_dict():
        raise PreOutcomeManifestError("manifest contract bytes changed")
    if observed.get("contract_sha256") != canonical_hash(contract.to_dict()):
        raise PreOutcomeManifestError("manifest contract hash changed")
    if observed.get("schema") != contract.schema:
        raise PreOutcomeManifestError("manifest schema differs from the contract")
    expected_evidence_class = (
        "production_preoutcome_manifest" if require_production else SYNTHETIC_EVIDENCE_CLASS
    )
    if observed.get("evidence_class") != expected_evidence_class:
        raise PreOutcomeManifestError("manifest evidence class differs from the contract")
    if canonical_hash(model_c) != contract.model_c_payload_sha256:
        raise PreOutcomeManifestError("Model-C payload differs from the frozen contract")
    if observed.get("estimand_contract") != to_jsonable(contract.estimand_contract):
        raise PreOutcomeManifestError("estimand contract changed")
    if observed.get("report_schema") != contract.report_schema:
        raise PreOutcomeManifestError("report schema changed")
    rows = observed.get("rows")
    if not isinstance(rows, list) or len(rows) != contract.expected_rows:
        raise PreOutcomeManifestError("manifest row count changed")
    row_keys = [str(row.get("row_key") or "") for row in rows if isinstance(row, dict)]
    if len(row_keys) != len(rows) or row_keys != sorted(row_keys):
        raise PreOutcomeManifestError("manifest rows are not in canonical order")
    if observed.get("outcomes_present") is not False:
        raise PreOutcomeManifestError("pre-outcome manifest claims outcome data")
    seen: set[str] = set()
    expected_row_hashes: list[str] = []
    scenarios: list[Scenario] = []
    indexed_scenarios: list[tuple[Scenario, int]] = []
    observed_support_masks: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PreOutcomeManifestError("manifest row is not an object")
        expected_keys = {
            "schema",
            "row_key",
            "scenario_id",
            "scenario",
            "scenario_hash",
            "configuration_id",
            "configuration_hash",
            "family",
            "family_index",
            "candidate_role",
            "opponent_role",
            "horizon",
            "public_state",
            "public_state_hash",
            "source",
            "eligibility",
            "eligibility_hash",
            "support_mask",
            "support_mask_hash",
            "receiver_contract_sha256",
            "rng_stream_sha256",
            "arm_rng_stream_sha256",
            "agent_entrypoints",
            "artifact_provenance_sha256",
            "dependency_sha256",
            "language_policy",
            "eprocess_contract",
            "retry_failure_policy",
            "missingness_policy",
            "row_sha256",
        }
        _assert_exact_keys(row, expected_keys, "manifest row")
        if row.get("schema") != ROW_SCHEMA:
            raise PreOutcomeManifestError("manifest row schema changed")
        row_without_hash = {key: value for key, value in row.items() if key != "row_sha256"}
        if row.get("row_sha256") != canonical_hash(row_without_hash):
            raise PreOutcomeManifestError("manifest row hash mismatch")
        key = str(row.get("row_key") or "")
        if not key or key in seen:
            raise PreOutcomeManifestError("duplicate or empty manifest row key")
        seen.add(key)
        if row.get("receiver_contract_sha256") != contract.receiver_contract_sha256:
            raise PreOutcomeManifestError("row receiver contract changed")
        if row.get("agent_entrypoints") != dict(contract.agent_entrypoints):
            raise PreOutcomeManifestError("row agent entrypoint changed")
        if row.get("artifact_provenance_sha256") != contract.artifact_provenance_sha256:
            raise PreOutcomeManifestError("row artifact provenance changed")
        if row.get("dependency_sha256") != dict(contract.dependency_sha256):
            raise PreOutcomeManifestError("row dependency hashes changed")
        if row.get("language_policy") != to_jsonable(contract.language_policy_contract):
            raise PreOutcomeManifestError("row language policy changed")
        if row.get("eprocess_contract") != to_jsonable(contract.eprocess_contract):
            raise PreOutcomeManifestError("row e-process contract changed")
        if row.get("retry_failure_policy") != to_jsonable(contract.retry_failure_policy):
            raise PreOutcomeManifestError("row retry/failure policy changed")
        if row.get("missingness_policy") != to_jsonable(contract.missingness_policy):
            raise PreOutcomeManifestError("row missingness policy changed")
        scenario_payload = row.get("scenario")
        if not isinstance(scenario_payload, dict):
            raise PreOutcomeManifestError("scenario payload is missing")
        try:
            scenario = Scenario(**copy.deepcopy(scenario_payload))
        except (TypeError, ValueError) as exc:
            raise PreOutcomeManifestError("scenario payload is malformed") from exc
        scenarios.append(scenario)
        family_index = row.get("family_index")
        if (
            not isinstance(family_index, int)
            or isinstance(family_index, bool)
            or family_index < 0
        ):
            raise PreOutcomeManifestError("scenario family index is malformed")
        indexed_scenarios.append((scenario, family_index))
        if row.get("scenario_hash") != canonical_hash(scenario):
            raise PreOutcomeManifestError("scenario hash mismatch")
        if (
            row.get("scenario_id") != scenario.scenario_id
            or row.get("family") != scenario.game_family
            or row.get("configuration_id") != scenario.config_id
            or row.get("candidate_role") != scenario.candidate_role
            or row.get("opponent_role") != scenario.opponent_role
            or row.get("source") != scenario.source
        ):
            raise PreOutcomeManifestError("row identity differs from scenario payload")
        if row.get("row_key") != f"{scenario.game_family}:{scenario.scenario_id}:{scenario.candidate_role}":
            raise PreOutcomeManifestError("row key differs from scenario payload")
        if row.get("configuration_hash") != canonical_hash(
            {"config_id": scenario.config_id, "public_parameters": scenario.public_parameters}
        ):
            raise PreOutcomeManifestError("configuration hash mismatch")
        if row.get("public_state") != scenario.public_parameters or row.get(
            "public_state_hash"
        ) != canonical_hash(scenario.public_parameters):
            raise PreOutcomeManifestError("public state changed")
        if row.get("horizon") != _horizon(scenario):
            raise PreOutcomeManifestError("horizon changed")
        allowed_roles = FAMILY_ROLES.get(scenario.game_family)
        if allowed_roles is None or scenario.candidate_role not in allowed_roles:
            raise PreOutcomeManifestError("scenario role is invalid")
        expected_opponent = (
            allowed_roles[1] if scenario.candidate_role == allowed_roles[0] else allowed_roles[0]
        )
        if scenario.opponent_role != expected_opponent:
            raise PreOutcomeManifestError("scenario roles are not complementary")
        expected_environment_seed = factorial_named_seed(
            contract.master_seed, scenario.scenario_id, "environment"
        )
        expected_opponent_seed = factorial_named_seed(
            contract.master_seed, scenario.scenario_id, "opponent-policy"
        )
        if int(scenario.seed) != expected_environment_seed or int(
            scenario.opponent_spec.get("seed", -1)
        ) != expected_opponent_seed:
            raise PreOutcomeManifestError("scenario named seeds changed")
        expected_eligibility = derive_factorial_eligibility(
            scenario,
            model_c=model_c,
            receiver_contract=contract.receiver_contract,
        )
        if row.get("eligibility") != expected_eligibility:
            raise PreOutcomeManifestError("eligibility changed after pre-outcome derivation")
        if row.get("eligibility_hash") != canonical_hash(expected_eligibility):
            raise PreOutcomeManifestError("eligibility hash mismatch")
        support_mask = row.get("support_mask")
        if not isinstance(support_mask, dict):
            raise PreOutcomeManifestError("support mask is malformed")
        if row.get("support_mask_hash") != canonical_hash(support_mask):
            raise PreOutcomeManifestError("support mask hash mismatch")
        observed_support_masks[scenario.scenario_id] = support_mask
        streams = row.get("rng_stream_sha256")
        if not isinstance(streams, dict) or set(streams) != set(NAMED_STREAMS):
            raise PreOutcomeManifestError("named RNG stream manifest is incomplete")
        if len(set(streams.values())) != len(streams):
            raise PreOutcomeManifestError("named RNG streams alias")
        if streams != _stream_manifest(
            contract, scenario, family_index=family_index
        ):
            raise PreOutcomeManifestError("named RNG stream hashes changed")
        expected_arm_streams = {
            arm: {
                "environment": streams["environment"],
                "economic": streams["candidate-economic"],
                "receiver": streams["controlled-receiver"],
                "evaluator": streams["factorial-evaluator"],
            }
            for arm in FACTORIAL_ARMS
        }
        if row.get("arm_rng_stream_sha256") != expected_arm_streams:
            raise PreOutcomeManifestError("arm-dependent economic/environment RNG is forbidden")
        expected_row_hashes.append(str(row["row_sha256"]))
    by_family_index: dict[str, set[int]] = defaultdict(set)
    for scenario, family_index in indexed_scenarios:
        if family_index in by_family_index[scenario.game_family]:
            raise PreOutcomeManifestError("duplicate scenario family index")
        by_family_index[scenario.game_family].add(family_index)
    for family, indices in by_family_index.items():
        if indices != set(range(contract.family_counts[family])):
            raise PreOutcomeManifestError("scenario family indices are not contiguous")
    if _indexed_scenario_design_sha256(indexed_scenarios) != contract.scenario_design_sha256:
        raise PreOutcomeManifestError("scenario design differs from the frozen contract")
    if support_masks_sha256(observed_support_masks) != contract.support_masks_sha256:
        raise PreOutcomeManifestError("support masks differ from the frozen contract")
    family_counts = Counter(str(row["family"]) for row in rows)
    if dict(sorted(family_counts.items())) != dict(sorted(contract.family_counts.items())):
        raise PreOutcomeManifestError("manifest family counts changed")
    if observed.get("family_counts") != dict(sorted(family_counts.items())):
        raise PreOutcomeManifestError("reported family counts mismatch rows")
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        role_counts[str(row["family"])][str(row["candidate_role"])] += 1
    expected_roles = {
        family: dict(sorted(counts.items())) for family, counts in sorted(role_counts.items())
    }
    for family, counts in role_counts.items():
        if set(counts) != set(FAMILY_ROLES[family]) or len(set(counts.values())) != 1:
            raise PreOutcomeManifestError("manifest roles are not balanced")
    if observed.get("role_counts") != expected_roles:
        raise PreOutcomeManifestError("reported role counts mismatch rows")
    if observed.get("row_count") != len(rows) or observed.get("arm_count") != 4 * len(rows):
        raise PreOutcomeManifestError("reported row/arm counts mismatch")
    if observed.get("row_root_sha256") != canonical_hash(expected_row_hashes):
        raise PreOutcomeManifestError("row root hash mismatch")
    without_hash = {key: value for key, value in observed.items() if key != "manifest_sha256"}
    if observed.get("manifest_sha256") != canonical_hash(without_hash):
        raise PreOutcomeManifestError("manifest root hash mismatch")


def validate_synthetic_preoutcome_manifest(
    manifest: Mapping[str, Any],
    *,
    contract: PreOutcomeManifestContract,
    model_c: Mapping[str, Any],
) -> dict[str, Any]:
    if contract.schema != SYNTHETIC_SCHEMA:
        raise PreOutcomeManifestError("synthetic validation requires synthetic schema")
    _validate_manifest_common(
        manifest,
        contract=contract,
        model_c=model_c,
        require_production=False,
    )
    if manifest.get("evidence_class") != SYNTHETIC_EVIDENCE_CLASS:
        raise PreOutcomeManifestError("synthetic manifest has a forged evidence class")
    return {
        "schema": "glee.research.preoutcome_manifest_validation.synthetic.v1",
        "passed": True,
        "evidence_class": SYNTHETIC_EVIDENCE_CLASS,
        "manifest_sha256": manifest["manifest_sha256"],
    }


def validate_production_preoutcome_manifest(
    manifest: Mapping[str, Any],
    *,
    contract: PreOutcomeManifestContract,
    model_c: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_manifest_common(
        manifest,
        contract=contract,
        model_c=model_c,
        require_production=True,
    )
    return {
        "schema": "glee.research.preoutcome_manifest_validation.production.v1",
        "passed": True,
        "evidence_class": "production_preoutcome_manifest",
        "manifest_sha256": manifest["manifest_sha256"],
    }


def validate_outcome_admission(
    manifest_row: Mapping[str, Any],
    admission: Mapping[str, Any],
    *,
    receiver_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate future arm inclusion/failure records without evaluating payoff."""

    _assert_exact_keys(
        admission,
        {"schema", "manifest_row_sha256", "arms"},
        "outcome admission",
    )
    if admission.get("schema") != OUTCOME_ADMISSION_SCHEMA:
        raise PreOutcomeManifestError("outcome admission schema is missing")
    if admission.get("manifest_row_sha256") != manifest_row.get("row_sha256"):
        raise PreOutcomeManifestError("outcome record is bound to another manifest row")
    arms = admission.get("arms")
    if not isinstance(arms, list) or {row.get("arm") for row in arms if isinstance(row, dict)} != set(
        FACTORIAL_ARMS
    ) or len(arms) != len(FACTORIAL_ARMS):
        raise PreOutcomeManifestError("outcome admission lacks exactly four arms")
    allowed_status = {"ok", "timeout", "refusal", "malformed", "missing"}
    if canonical_hash(receiver_contract) != manifest_row.get("receiver_contract_sha256"):
        raise PreOutcomeManifestError("outcome admission uses another receiver contract")
    output_contract = receiver_contract.get("output_contract")
    if not isinstance(output_contract, Mapping):
        raise PreOutcomeManifestError("receiver output contract is missing")
    for row in arms:
        if not isinstance(row, dict):
            raise PreOutcomeManifestError("outcome arm admission is malformed")
        _assert_exact_keys(
            row,
            {"arm", "included_in_intent_to_treat", "receiver_envelope"},
            "outcome arm admission",
        )
        if row.get("included_in_intent_to_treat") is not True:
            raise PreOutcomeManifestError("post-treatment exclusion is forbidden")
        receiver = row.get("receiver_envelope")
        if not isinstance(receiver, dict):
            raise PreOutcomeManifestError("receiver output envelope is missing")
        _assert_exact_keys(
            receiver,
            {"schema", "status", "request_sha256", "response_sha256", "parsed_output"},
            "receiver output envelope",
        )
        if receiver.get("schema") != "glee.research.controlled_receiver_envelope.v1":
            raise PreOutcomeManifestError("receiver output envelope schema is malformed")
        if receiver.get("status") not in allowed_status:
            raise PreOutcomeManifestError("receiver output status is malformed")
        if not _is_sha256(receiver.get("request_sha256")):
            raise PreOutcomeManifestError("receiver request hash is missing")
        response_hash = receiver.get("response_sha256")
        if receiver.get("status") == "ok":
            if not _is_sha256(response_hash) or receiver.get("parsed_output") is None:
                raise PreOutcomeManifestError("successful receiver output is malformed")
            _validate_receiver_parsed_output(receiver.get("parsed_output"), output_contract)
        elif response_hash is not None and not _is_sha256(response_hash):
            raise PreOutcomeManifestError("failed receiver output hash is malformed")
        elif receiver.get("parsed_output") is not None:
            raise PreOutcomeManifestError("failed receiver output must not contain parsed output")
    return {
        "schema": "glee.research.factorial_outcome_admission_validation.v1",
        "passed": True,
        "evidence_class": SYNTHETIC_EVIDENCE_CLASS,
        "manifest_row_sha256": manifest_row["row_sha256"],
    }


def _validate_receiver_parsed_output(
    parsed_output: Any,
    output_contract: Mapping[str, Any],
) -> None:
    """Validate the frozen strict receiver JSON schema used by outcome admission.

    The controlled receiver deliberately supports a small strict-object surface.
    This validator does not pretend to be a general JSON-Schema implementation.
    """

    if not isinstance(parsed_output, dict):
        raise PreOutcomeManifestError("successful receiver parsed output is not an object")
    schema = output_contract.get("schema")
    if not isinstance(schema, Mapping):
        raise PreOutcomeManifestError("receiver output schema is missing")
    properties = schema.get("properties")
    required = schema.get("required")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, Mapping)
        or not isinstance(required, list)
    ):
        raise PreOutcomeManifestError("receiver output schema is not strict")
    if not set(required).issubset(parsed_output) or not set(parsed_output).issubset(properties):
        raise PreOutcomeManifestError("successful receiver parsed output fields are malformed")
    supported_types = {
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: isinstance(value, (int, float))
        and not isinstance(value, bool)
        and not isinstance(value, float)
        or (
            isinstance(value, float)
            and math.isfinite(value)
        ),
        "boolean": lambda value: type(value) is bool,
        "null": lambda value: value is None,
    }
    for key, value in parsed_output.items():
        rule = properties.get(key)
        if not isinstance(rule, Mapping) or rule.get("type") not in supported_types:
            raise PreOutcomeManifestError("receiver output property schema is unsupported")
        if not supported_types[str(rule["type"])](value):
            raise PreOutcomeManifestError("successful receiver parsed output type is malformed")
        if "enum" in rule and value not in list(rule.get("enum") or []):
            raise PreOutcomeManifestError("successful receiver parsed output enum is malformed")
    decision_field = str(output_contract.get("decision_field") or "")
    allowed = [
        *list(output_contract.get("allowed_decisions") or []),
        *list(output_contract.get("refusal_decisions") or []),
    ]
    decision_schema = properties.get(decision_field)
    if (
        not decision_field
        or decision_field not in required
        or not isinstance(decision_schema, Mapping)
        or decision_schema.get("type") != "string"
        or list(decision_schema.get("enum") or []) != allowed
        or parsed_output.get(decision_field) not in allowed
    ):
        raise PreOutcomeManifestError("successful receiver decision is malformed")
