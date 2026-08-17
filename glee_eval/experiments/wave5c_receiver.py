"""Wave 5C's provider-neutral controlled-receiver decision infrastructure.

The module freezes a concrete *proposal* and validates its arithmetic, hashes,
input separation, and exact-cache behavior.  It contains no provider client and
cannot make an external call.  A proposal or synthetic dry run is not a
production authorization or treatment-effect result.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from glee_eval.experiments.controlled_receiver import (
    CACHE_MODE,
    INFRASTRUCTURE_ONLY_NON_EVIDENCE,
    MISSINGNESS_RULE,
    CallReservation,
    CapabilityCertificate,
    CapabilityProbe,
    ContractValidationError,
    ControlledReceiverHarness,
    ReceiverContract,
    RequestEnvelope,
    TransportResult,
    Usage,
    canonical_json_bytes,
    certify_capability,
)


PROPOSAL_SCHEMA = "glee.research.wave5c.receiver_proposal.v1"
DRY_RUN_SCHEMA = "glee.research.wave5c.receiver_dry_run.v1"
PROPOSAL_STATUS = "candidate_requires_user_decision_credentials_and_independent_audit"
DESIGN_ID = "design_a_300_strata_x_2_roles_x_2_receiver_replicates"
FIELD_NAMES = (
    "identity",
    "independent_selection_provenance",
    "prompt_bytes",
    "input_boundary",
    "generation",
    "output_parser",
    "failure_policy",
    "cache_retention",
    "resource_caps",
    "scope",
    "capability_design",
    "confirmatory_design",
    "adapter",
)

SYSTEM_PROMPT_BYTES = (
    b"You are the controlled buyer in a persuasion game. Decide only from the "
    b"supplied public state, fixed seller recommendation, and candidate message. "
    b"Do not infer or request hidden information. Return exactly one JSON object "
    b"matching the supplied schema and no other text."
)
USER_PROMPT_BYTES = (
    b"Evaluate the candidate message while holding the economic recommendation fixed. "
    b"Use only inputs.visible, inputs.economic_stance, and inputs.candidate_text. "
    b"Return {\"decision\":\"buy\"}, {\"decision\":\"pass\"}, or "
    b"{\"decision\":\"refuse\"}."
)

VISIBLE_INPUT_FIELDS = (
    "round",
    "total_rounds",
    "product_price",
    "prior_probability_high_quality",
    "buyer_value_high_quality",
    "buyer_value_low_quality",
    "seller_message_type",
    "is_myopic",
    "prior_public_recommendations",
    "prior_public_buyer_decisions",
)
HIDDEN_INPUT_FIELDS = (
    "treatment_arm",
    "scenario_id",
    "candidate_private_quality",
    "template_id",
    "eprocess_state",
    "future_events",
    "terminal_outcome",
    "candidate_payoff",
    "opponent_payoff",
)
RECEIVER_SEEDS = (530011, 530017)
GENERIC_TEXT_A = "After weighing only the public evidence, proceed if it supports the purchase."
GENERIC_TEXT_B = "After weighing only the public evidence, do not proceed with the purchase."


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@dataclass(frozen=True)
class ReceiverCallAccounting:
    """Exact accounting for frozen Design A and the 20-round persuasion game."""

    families: int = 3
    base_strata_per_family: int = 300
    roles_per_family: int = 2
    receiver_replicates: int = 2
    factorial_arms: int = 4
    persuasion_rounds: int = 20
    maximum_attempts: int = 2
    capability_states: int = 25
    capability_texts_per_state: int = 2

    @property
    def rows_per_family(self) -> int:
        return self.base_strata_per_family * self.roles_per_family * self.receiver_replicates

    @property
    def paired_scenario_rows(self) -> int:
        return self.families * self.rows_per_family

    @property
    def agent_executions(self) -> int:
        return self.paired_scenario_rows * self.factorial_arms

    @property
    def receiver_eligible_rows(self) -> int:
        # Only persuasion candidate-seller rows are language eligible.
        return self.base_strata_per_family * self.receiver_replicates

    @property
    def confirmatory_nominal_requests(self) -> int:
        return self.receiver_eligible_rows * self.factorial_arms * self.persuasion_rounds

    @property
    def confirmatory_max_attempts(self) -> int:
        return self.confirmatory_nominal_requests * self.maximum_attempts

    @property
    def capability_nominal_requests(self) -> int:
        return (
            self.capability_states
            * self.capability_texts_per_state
            * self.receiver_replicates
        )

    @property
    def capability_max_attempts(self) -> int:
        return self.capability_nominal_requests * self.maximum_attempts

    @property
    def total_nominal_requests(self) -> int:
        return self.capability_nominal_requests + self.confirmatory_nominal_requests

    @property
    def total_max_attempts(self) -> int:
        return self.capability_max_attempts + self.confirmatory_max_attempts

    def to_dict(self) -> dict[str, Any]:
        return {
            "meaning_of_3600": "paired_scenario_rows_reused_by_all_four_arms",
            "design": DESIGN_ID,
            "families": self.families,
            "base_strata_per_family": self.base_strata_per_family,
            "roles_per_family": self.roles_per_family,
            "receiver_replicates": self.receiver_replicates,
            "rows_per_family": self.rows_per_family,
            "paired_scenario_rows": self.paired_scenario_rows,
            "factorial_arms": self.factorial_arms,
            "agent_executions": self.agent_executions,
            "receiver_scope": "persuasion_candidate_seller_only",
            "receiver_eligible_rows": self.receiver_eligible_rows,
            "receiver_decisions_per_execution": self.persuasion_rounds,
            "confirmatory_nominal_requests": self.confirmatory_nominal_requests,
            "confirmatory_planned_retries": 0,
            "confirmatory_additional_retry_cap": (
                self.confirmatory_max_attempts - self.confirmatory_nominal_requests
            ),
            "confirmatory_max_attempts": self.confirmatory_max_attempts,
            "capability_states": self.capability_states,
            "capability_texts_per_state": self.capability_texts_per_state,
            "capability_nominal_requests": self.capability_nominal_requests,
            "capability_planned_retries": 0,
            "capability_additional_retry_cap": (
                self.capability_max_attempts - self.capability_nominal_requests
            ),
            "capability_max_attempts": self.capability_max_attempts,
            "total_nominal_requests": self.total_nominal_requests,
            "total_planned_retries": 0,
            "total_max_attempts": self.total_max_attempts,
            "cache_hits_reduce_external_calls_but_are_not_assumed_in_caps": True,
        }


def build_receiver_contract() -> ReceiverContract:
    """Return the concrete primary proposal in the existing canonical format."""

    accounting = ReceiverCallAccounting()
    return ReceiverContract(
        contract_id="wave5c.primary.openai_gpt41_2025_04_14.persuasion_buyer.v1",
        provider="openai",
        model="gpt-4.1",
        version="gpt-4.1-2025-04-14",
        local_artifact_sha256=None,
        system_prompt_bytes=SYSTEM_PROMPT_BYTES,
        user_prompt_bytes=USER_PROMPT_BYTES,
        visible_input_fields=VISIBLE_INPUT_FIELDS,
        hidden_input_fields=HIDDEN_INPUT_FIELDS,
        candidate_text_field="candidate_text",
        economic_stance_field="economic_stance",
        decoding_parameters={
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 16,
            "response_format": "strict_json_schema",
            "receiver_seed_scope": "request_identity_only_not_provider_parameter",
        },
        receiver_seeds=RECEIVER_SEEDS,
        parser_id="strict_json_decision_v1",
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["buy", "pass", "refuse"],
                }
            },
            "required": ["decision"],
        },
        decision_field="decision",
        allowed_decisions=("buy", "pass"),
        refusal_decisions=("refuse",),
        failure_actions={
            "timeout": "retry_then_record_missing",
            "refusal": "record_missing",
            "malformed": "retry_then_record_missing",
            "missing": "record_missing",
        },
        max_attempts=accounting.maximum_attempts,
        timeout_seconds=30.0,
        missingness_rule=MISSINGNESS_RULE,
        cache_mode=CACHE_MODE,
        max_calls=accounting.total_max_attempts,
        max_input_tokens=accounting.total_max_attempts * 2048,
        max_output_tokens=accounting.total_max_attempts * 16,
        max_cost_microusd=1_000_000_000,
        max_runtime_seconds=accounting.total_max_attempts * 30.0,
        eligible_family="persuasion",
        eligible_candidate_role="seller",
        receiver_role="buyer",
        receiver_selection_rule=(
            "user/principal investigator prospectively selects the pre-existing immutable "
            "receiver before capability or factorial outcomes; fallback is not automatic"
        ),
        receiver_selection_is_treatment_blind=True,
        selection_frozen_before_treatment=True,
        selection_uses_factorial_payoff=False,
        selection_uses_treatment_templates=False,
    )


def build_proposal() -> dict[str, Any]:
    accounting = ReceiverCallAccounting()
    contract = build_receiver_contract()
    fields: dict[str, Any] = {
        "identity": {
            "primary": {
                "provider": "openai",
                "model": "gpt-4.1",
                "immutable_version": "gpt-4.1-2025-04-14",
                "endpoint_family": "Responses API",
                "status": "proposed_not_authorized_or_capability_verified",
            },
            "fallback": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "immutable_version": "gpt-4.1-mini-2025-04-14",
                "endpoint_family": "Responses API",
                "activation": "requires_new_explicit_authorization_after_primary_route_closes",
            },
            "receiver_contract_sha256": contract.sha256,
            "user_decision_required": "accept_primary_or_reject_and_select_fallback",
        },
        "independent_selection_provenance": {
            "proposed_owner_role": "user_principal_investigator",
            "selection_rule": (
                "pre-existing receiver selected without capability strength, four treatment "
                "templates, Factorial01/11 actions, or any factorial payoff"
            ),
            "owner_name": "USER_MUST_RECORD_NAME",
            "selection_timestamp_utc": "USER_MUST_RECORD_AT_AUTHORIZATION",
            "affirmation_required": True,
        },
        "prompt_bytes": {
            "encoding": "utf-8",
            "system_b64": _b64(SYSTEM_PROMPT_BYTES),
            "system_sha256": _sha256(SYSTEM_PROMPT_BYTES),
            "user_b64": _b64(USER_PROMPT_BYTES),
            "user_sha256": _sha256(USER_PROMPT_BYTES),
        },
        "input_boundary": {
            "candidate_text_field": "candidate_text",
            "economic_stance_field": "economic_stance",
            "economic_stance_schema": {"recommendation": "yes_or_no"},
            "visible_fields": list(VISIBLE_INPUT_FIELDS),
            "hidden_fields": list(HIDDEN_INPUT_FIELDS),
            "hidden_values_committed_by_hash_but_never_sent": True,
        },
        "generation": {
            "parameters": {
                "temperature": 0,
                "top_p": 1,
                "max_output_tokens": 16,
                "response_format": "strict_json_schema",
                "receiver_seed_scope": "request_identity_only_not_provider_parameter",
            },
            "receiver_seeds": list(RECEIVER_SEEDS),
            "provider_seed_parameter_sent": False,
            "receiver_seeds_partition_requests_and_cache_only": True,
            "expected_byte_determinism": False,
        },
        "output_parser": contract.to_dict()["output_contract"],
        "failure_policy": {
            **contract.to_dict()["failure_contract"],
            "backoff_seconds": 0,
            "jitter": False,
            "retry_scope": ["timeout", "malformed"],
            "refusal_and_missing_are_not_retried": True,
        },
        "cache_retention": {
            "mode": CACHE_MODE,
            "namespace": "contract_sha256/request_sha256",
            "replay": "exact_cached_envelope_only_zero_external_calls",
            "conflict": "abort_do_not_overwrite",
            "proposed_storage": "research/private_cache/wave5c_receiver",
            "encryption": "required_at_rest",
            "access": "principal_investigator_and_named_runner_only",
            "retention_days": 180,
            "user_decisions_required": ["storage_location", "retention", "access_policy"],
            "invalidation": (
                "any identity, prompt, input, decoding, parser, failure, adapter, dependency, "
                "or execution-stack change creates a new contract hash and cache namespace"
            ),
        },
        "resource_caps": {
            "per_attempt": {
                "input_tokens": 2048,
                "output_tokens": 16,
                "cost_microusd": 10_000,
                "timeout_seconds": 30,
            },
            "study_plus_capability": {
                "max_attempts": accounting.total_max_attempts,
                "max_input_tokens": accounting.total_max_attempts * 2048,
                "max_output_tokens": accounting.total_max_attempts * 16,
                "max_cost_microusd": 1_000_000_000,
                "max_wall_runtime_hours": 12,
                "max_concurrency": 32,
            },
            "planning_price_snapshot_2026_08_16": {
                "primary_input_usd_per_million_tokens": 2.0,
                "primary_output_usd_per_million_tokens": 8.0,
                "primary_nominal_reserved_cost_usd": 203.1744,
                "primary_hard_attempt_cap_reserved_cost_usd": 406.3488,
                "fallback_input_usd_per_million_tokens": 0.4,
                "fallback_output_usd_per_million_tokens": 1.6,
                "fallback_hard_attempt_cap_reserved_cost_usd": 81.26976,
                "capability_only_primary_nominal_reserved_cost_usd": 0.4224,
                "capability_only_primary_hard_cap_reserved_cost_usd": 0.8448,
            },
            "pricing_must_be_reverified_on_authorization_date": True,
            "spend_authorization_required_usd": 1000,
        },
        "scope": {
            "eligible": "persuasion_candidate_seller_receiver_buyer_text_configuration",
            "persuasion_rounds": 20,
            "bargaining": "no_external_receiver_language_negative_control",
            "negotiation": "no_external_receiver_language_negative_control",
            "persuasion_candidate_buyer": "no_external_receiver_wrong_intervention_direction",
            "numeric_action_or_stance_is_fixed_before_receiver_input": True,
        },
        "capability_design": {
            "states": accounting.capability_states,
            "texts_per_state": accounting.capability_texts_per_state,
            "receiver_replicates": accounting.receiver_replicates,
            "nominal_requests": accounting.capability_nominal_requests,
            "maximum_attempts": accounting.capability_max_attempts,
            "generic_text_sha256": [
                _sha256(GENERIC_TEXT_A.encode("utf-8")),
                _sha256(GENERIC_TEXT_B.encode("utf-8")),
            ],
            "pass_rule": (
                "all delivery, consumed-field, hidden-input, parser-invariance, and replay "
                "checks pass; at least 5 of 25 states change decision in each replicate"
            ),
            "probes_are_not_treatment_templates": True,
            "fresh_independent_probe_owner_audit_required": True,
            "failed_probes_are_not_replaced": True,
        },
        "confirmatory_design": {
            **accounting.to_dict(),
            "four_agent_entrypoints_unchanged": [
                "Factorial00Agent",
                "Factorial10Agent",
                "Factorial01Agent",
                "Factorial11Agent",
            ],
            "design_recommendation": "A",
            "design_reason": (
                "the proposed hosted receiver is not expected to be byte-deterministic; two "
                "receiver replicates measure variance while retaining 300 economic strata"
            ),
            "production_authorization_pins": "remain_unset",
        },
        "adapter": {
            "protocol": "ReceiverTransport(bytes, timeout_seconds) -> TransportResult",
            "provider_neutral_harness": "glee_eval.experiments.controlled_receiver",
            "external_provider_adapter": "USER_MUST_SUPPLY_REVIEWED_MODULE_AND_SHA256",
            "credential_environment_names": ["OPENAI_API_KEY"],
            "credential_values_never_serialized_or_hashed": True,
            "required_consumed_field_attestation": (
                "adapter_records_candidate_text_serialized_to_provider_request; this is not "
                "provider-internal attention telemetry"
            ),
            "provider_internal_consumption_attestation": "unverified_unless_provider_exposes_it",
            "provider_model_seed_schema_support_must_be_verified": True,
            "dry_run_transport": "glee_eval.experiments.wave5c_receiver:dry_run_transport",
            "dry_run_transport_is_ineligible_for_production": True,
        },
    }
    return {
        "schema": PROPOSAL_SCHEMA,
        "status": PROPOSAL_STATUS,
        "evidence_label": INFRASTRUCTURE_ONLY_NON_EVIDENCE,
        "fields": fields,
        "user_decisions_and_credentials": [
            "accept primary identity or explicitly reject it and select the fallback",
            "record independent selector name, UTC time, and treatment-blind affirmation",
            "provide OPENAI_API_KEY only through the runner environment",
            "approve the USD 1000 hard ceiling after current pricing is verified",
            "approve encrypted cache location, access list, and 180-day retention",
            "supply and audit the provider adapter source/dependency hashes",
            "authorize capability calls separately; a payoff run needs a later authorization",
        ],
        "hard_boundaries": {
            "external_calls_performed": False,
            "payoff_study_performed": False,
            "production_pins_set": False,
            "fallback_automatic": False,
        },
    }


def validate_proposal(proposal: Mapping[str, Any]) -> None:
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise ContractValidationError("Wave 5C receiver proposal schema mismatch")
    fields = proposal.get("fields")
    if not isinstance(fields, Mapping) or set(fields) != set(FIELD_NAMES):
        raise ContractValidationError("receiver proposal must contain exactly the 13 fields")
    prompt = fields["prompt_bytes"]
    for name, expected in (("system", SYSTEM_PROMPT_BYTES), ("user", USER_PROMPT_BYTES)):
        try:
            decoded = base64.b64decode(prompt[f"{name}_b64"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise ContractValidationError("invalid prompt bytes") from exc
        if decoded != expected or prompt[f"{name}_sha256"] != _sha256(expected):
            raise ContractValidationError("prompt hash or exact bytes changed")
    boundary = fields["input_boundary"]
    visible = tuple(boundary.get("visible_fields", ()))
    hidden = tuple(boundary.get("hidden_fields", ()))
    if visible != VISIBLE_INPUT_FIELDS or hidden != HIDDEN_INPUT_FIELDS:
        raise ContractValidationError("visible/hidden input boundary changed")
    if set(visible) & set(hidden) or "treatment_arm" not in hidden:
        raise ContractValidationError("hidden treatment separation is invalid")
    accounting = ReceiverCallAccounting().to_dict()
    confirmatory = fields["confirmatory_design"]
    for key, expected in accounting.items():
        if confirmatory.get(key) != expected:
            raise ContractValidationError(f"receiver call accounting changed: {key}")
    contract = build_receiver_contract()
    if fields["identity"].get("receiver_contract_sha256") != contract.sha256:
        raise ContractValidationError("canonical receiver contract hash mismatch")
    if proposal.get("evidence_label") != INFRASTRUCTURE_ONLY_NON_EVIDENCE:
        raise ContractValidationError("proposal has an invalid evidence label")
    boundaries = proposal.get("hard_boundaries", {})
    if any(boundaries.get(key) is not False for key in (
        "external_calls_performed",
        "payoff_study_performed",
        "production_pins_set",
        "fallback_automatic",
    )):
        raise ContractValidationError("proposal crosses a Wave 5C hard boundary")
    if canonical_json_bytes(proposal) != canonical_json_bytes(build_proposal()):
        raise ContractValidationError("an exact proposed receiver-contract value changed")


def proposal_sha256(proposal: Mapping[str, Any] | None = None) -> str:
    value = build_proposal() if proposal is None else proposal
    validate_proposal(value)
    return _sha256(canonical_json_bytes(value))


def build_capability_probes() -> tuple[CapabilityProbe, ...]:
    """Return 25 public-state strata crossed with the two receiver replicates."""

    probes = []
    for state_index in range(25):
        for seed in RECEIVER_SEEDS:
            probes.append(
                CapabilityProbe(
                    probe_id=f"wave5c-generic-{state_index:02d}-seed-{seed}",
                    candidate_text_a=GENERIC_TEXT_A,
                    candidate_text_b=GENERIC_TEXT_B,
                    economic_stance={"recommendation": "yes" if state_index % 2 else "no"},
                    visible_inputs={
                        "round": 1 + state_index % 20,
                        "total_rounds": 20,
                        "product_price": (100, 10_000, 1_000_000)[state_index % 3],
                        "prior_probability_high_quality": (0.3333333333333333, 0.5, 0.8)[state_index % 3],
                        "buyer_value_high_quality": (1.2, 1.25, 2.0, 3.0, 4.0)[state_index % 5],
                        "buyer_value_low_quality": 0.0,
                        "seller_message_type": "text",
                        "is_myopic": bool(state_index % 2),
                        "prior_public_recommendations": [],
                        "prior_public_buyer_decisions": [],
                    },
                    hidden_inputs={
                        "treatment_arm": "HIDDEN_CAPABILITY_NOT_FACTORIAL",
                        "scenario_id": f"hidden-capability-{state_index:02d}",
                        "candidate_private_quality": "HIDDEN_CANARY_QUALITY",
                        "template_id": "HIDDEN_CANARY_TEMPLATE",
                        "eprocess_state": "HIDDEN_CANARY_EPROCESS",
                        "future_events": "HIDDEN_CANARY_FUTURE",
                        "terminal_outcome": "HIDDEN_CANARY_TERMINAL",
                        "candidate_payoff": "HIDDEN_CANARY_PAYOFF",
                        "opponent_payoff": "HIDDEN_CANARY_OPPONENT_PAYOFF",
                    },
                    seed=seed,
                )
            )
    return tuple(probes)


def dry_run_transport(outbound: bytes, _timeout_seconds: float) -> TransportResult:
    """Deterministic local test double; never eligible as the paper receiver."""

    value = json.loads(outbound)
    text = value["inputs"]["candidate_text"]
    decision = "buy" if "proceed if" in text else "pass"
    return TransportResult(
        canonical_json_bytes({"decision": decision}),
        Usage(input_tokens=256, output_tokens=4, cost_microusd=0),
        elapsed_ms=0,
        consumed_fields=("candidate_text",),
    )


def capability_rule_summary(certificate: CapabilityCertificate) -> dict[str, Any]:
    """Apply Wave 5C's stronger, replicate-specific prospective pass rule."""

    expected_ids = {probe.probe_id for probe in build_capability_probes()}
    observed_ids = {str(item.get("probe_id")) for item in certificate.probe_results}
    changed_by_seed = {str(seed): 0 for seed in RECEIVER_SEEDS}
    for item in certificate.probe_results:
        probe_id = str(item.get("probe_id"))
        for seed in RECEIVER_SEEDS:
            if probe_id.endswith(f"-seed-{seed}") and item.get("output_changed") is True:
                changed_by_seed[str(seed)] += 1
    plumbing_checks = {
        "candidate_text_delivered": certificate.candidate_text_delivered,
        "receiver_consumes_candidate_text": certificate.receiver_consumes_candidate_text,
        "hidden_treatment_information_not_exposed": (
            certificate.hidden_treatment_information_not_exposed
        ),
        "parsing_and_failures_arm_invariant": certificate.parsing_and_failures_arm_invariant,
        "exact_cache_replay": certificate.exact_cache_replay,
    }
    return {
        "expected_probe_ids_complete": observed_ids == expected_ids,
        "plumbing_checks": plumbing_checks,
        "changed_states_by_receiver_seed": changed_by_seed,
        "minimum_changed_states_per_receiver_seed": 5,
        "passed": (
            observed_ids == expected_ids
            and all(plumbing_checks.values())
            and all(count >= 5 for count in changed_by_seed.values())
        ),
    }


def build_dry_run_report() -> dict[str, Any]:
    proposal = build_proposal()
    validate_proposal(proposal)
    contract = build_receiver_contract()
    probes = build_capability_probes()
    certificate = certify_capability(
        contract,
        probes,
        transport=dry_run_transport,
        reservation=CallReservation(
            input_tokens=2048,
            max_output_tokens=16,
            max_cost_microusd=10_000,
        ),
    )
    wave5c_rule = capability_rule_summary(certificate)
    canary = probes[0]
    left = RequestEnvelope.build(
        contract,
        probe_id="hostile-hidden-arm-00",
        candidate_text=GENERIC_TEXT_A,
        economic_stance=canary.economic_stance,
        visible_inputs=canary.visible_inputs,
        hidden_inputs={**dict(canary.hidden_inputs), "treatment_arm": "e0_l0"},
        seed=canary.seed,
    )
    right = RequestEnvelope.build(
        contract,
        probe_id="hostile-hidden-arm-11",
        candidate_text=GENERIC_TEXT_A,
        economic_stance=canary.economic_stance,
        visible_inputs=canary.visible_inputs,
        hidden_inputs={**dict(canary.hidden_inputs), "treatment_arm": "e1_l1"},
        seed=canary.seed,
    )
    outbound_text = left.outbound_bytes.decode("utf-8")
    hidden_canaries_absent = all(
        key not in outbound_text and str(value) not in outbound_text
        for key, value in canary.hidden_inputs.items()
    )
    replay_harness = ControlledReceiverHarness(contract)
    original = replay_harness.invoke(
        left,
        reservation=CallReservation(2048, 16, 10_000),
        transport=dry_run_transport,
    )
    replay = replay_harness.invoke(
        left,
        reservation=CallReservation(2048, 16, 10_000),
        replay_only=True,
    )
    cache_bytes = replay_harness.cache.dump_bytes()
    return {
        "schema": DRY_RUN_SCHEMA,
        "status": "self_audited_infrastructure_only",
        "evidence_label": INFRASTRUCTURE_ONLY_NON_EVIDENCE,
        "proposal_sha256": proposal_sha256(proposal),
        "receiver_contract_sha256": contract.sha256,
        "parser_and_failure_sha256": contract.parser_and_failure_sha256,
        "capability_probe_count": len(probes),
        "capability_nominal_requests": len(probes) * 2,
        "synthetic_certificate_sha256": certificate.sha256,
        "synthetic_certificate_passed": certificate.passed,
        "wave5c_capability_rule": wave5c_rule,
        "hostile_checks": {
            "hidden_arm_changes_request_hash": left.request_sha256 != right.request_sha256,
            "hidden_arm_does_not_change_outbound_bytes": left.outbound_bytes == right.outbound_bytes,
            "hidden_names_and_canary_values_absent_from_outbound": hidden_canaries_absent,
            "exact_replay_is_cache_hit": replay.cache_hit,
            "exact_replay_bytes_identical": replay.record.to_bytes() == original.record.to_bytes(),
            "replay_used_zero_additional_transport_calls": replay_harness.budget.calls == 1,
        },
        "cache_sha256": _sha256(cache_bytes),
        "external_calls_performed": False,
        "payoff_rows_generated": 0,
        "production_authorization_pins_changed": False,
        "scientific_claim": "none_synthetic_transport_only",
    }


def render_evidence() -> bytes:
    return canonical_json_bytes(
        {
            "schema": "glee.research.wave5c.receiver_evidence.v1",
            "proposal": build_proposal(),
            "dry_run": build_dry_run_report(),
        }
    )


__all__ = [
    "DESIGN_ID",
    "DRY_RUN_SCHEMA",
    "FIELD_NAMES",
    "PROPOSAL_SCHEMA",
    "ReceiverCallAccounting",
    "build_capability_probes",
    "build_dry_run_report",
    "build_proposal",
    "build_receiver_contract",
    "capability_rule_summary",
    "dry_run_transport",
    "proposal_sha256",
    "render_evidence",
    "validate_proposal",
]
