"""Fail-closed infrastructure for a future frozen text-responsive receiver.

This module performs no network or model calls.  A caller must inject a
``ReceiverTransport`` after separately authorizing and freezing a receiver.
Capability certificates produced here are infrastructure checks, never payoff
or treatment-effect evidence.
"""

from __future__ import annotations

import base64
import argparse
import hashlib
import importlib
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


CONTRACT_SCHEMA = "glee.research.controlled_receiver_contract.v1"
REQUEST_SCHEMA = "glee.research.controlled_receiver_request.v1"
RESPONSE_SCHEMA = "glee.research.controlled_receiver_response.v1"
CACHE_SCHEMA = "glee.research.controlled_receiver_cache.v1"
CERTIFICATE_SCHEMA = "glee.research.receiver_capability_certificate.v1"
INFRASTRUCTURE_ONLY_NON_EVIDENCE = "infrastructure_only_non_evidence"
MISSINGNESS_RULE = "retain_prespecified_row_mark_missing_no_post_treatment_exclusion"
CACHE_MODE = "exact_envelope_sha256_read_write_replay"

# SHA-256 values of the four Wave-3 treatment strings.  Their text is
# deliberately not imported into this generic certification surface.
_TREATMENT_TEMPLATE_SHA256 = frozenset(
    {
        "4677b569fb5078b2fc08e73da91a74f7d633b89ef47e81d3a2ea84a4caf21241",
        "e16ee71af4790ad821b6407c92b1d7f84ad0672101f7866e5852f71dfbbda00f",
        "167b0d3bef8906fa88252af3c494dcaadf4754e9a5cfdcda27db8d217f97b05d",
        "17eedfdea36dc04457ad1d96081aa859ebe3363b40b27bb3af5a0a57e357901f",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_KINDS = ("timeout", "refusal", "malformed", "missing")
_FAILURE_ACTIONS = {"record_missing", "retry_then_record_missing"}


class ControlledReceiverError(RuntimeError):
    """Base class for receiver-contract failures."""


class ContractValidationError(ControlledReceiverError):
    pass


class EnvelopeIntegrityError(ControlledReceiverError):
    pass


class CacheMiss(ControlledReceiverError):
    pass


class BudgetExceeded(ControlledReceiverError):
    pass


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"value is not finite canonical JSON: {type(value).__name__}")


def _immutable_json(value: Any) -> Any:
    plain = _plain_json(value)
    if isinstance(plain, dict):
        return MappingProxyType({key: _immutable_json(item) for key, item in plain.items()})
    if isinstance(plain, list):
        return tuple(_immutable_json(item) for item in plain)
    return plain


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _plain_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, name: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise ContractValidationError(f"{name} must be a lowercase SHA-256 hex digest")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise EnvelopeIntegrityError("invalid base64 in frozen envelope") from exc


def _contains_mapping_key(value: Any, forbidden: str) -> bool:
    if isinstance(value, Mapping):
        return forbidden in value or any(
            _contains_mapping_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_mapping_key(item, forbidden) for item in value)
    return False


@dataclass(frozen=True)
class ReceiverContract:
    """Canonical, hash-addressed receiver contract.

    A hosted receiver must freeze provider/model/version.  A local receiver may
    instead be identified by an artifact hash.  The selection gates make
    treatment-based or factorial-payoff-based receiver selection invalid.
    """

    contract_id: str
    provider: str
    model: str
    version: str
    local_artifact_sha256: str | None
    system_prompt_bytes: bytes
    user_prompt_bytes: bytes
    visible_input_fields: tuple[str, ...]
    hidden_input_fields: tuple[str, ...]
    candidate_text_field: str
    economic_stance_field: str
    decoding_parameters: Mapping[str, Any]
    receiver_seeds: tuple[int, ...]
    parser_id: str
    output_schema: Mapping[str, Any]
    decision_field: str
    allowed_decisions: tuple[str, ...]
    refusal_decisions: tuple[str, ...]
    failure_actions: Mapping[str, str]
    max_attempts: int
    timeout_seconds: float
    missingness_rule: str
    cache_mode: str
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_microusd: int
    max_runtime_seconds: float
    eligible_family: str
    eligible_candidate_role: str
    receiver_role: str
    receiver_selection_rule: str
    receiver_selection_is_treatment_blind: bool
    selection_frozen_before_treatment: bool
    selection_uses_factorial_payoff: bool
    selection_uses_treatment_templates: bool
    schema: str = field(default=CONTRACT_SCHEMA, init=False)

    def __post_init__(self) -> None:
        text_fields = (
            "contract_id",
            "candidate_text_field",
            "economic_stance_field",
            "parser_id",
            "decision_field",
            "eligible_family",
            "eligible_candidate_role",
            "receiver_role",
            "receiver_selection_rule",
        )
        for name in text_fields:
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ContractValidationError(f"{name} must be a non-empty string")

        for name in ("provider", "model", "version"):
            if not isinstance(getattr(self, name), str):
                raise ContractValidationError(f"{name} must be a string")

        hosted_identity = all(value.strip() for value in (self.provider, self.model, self.version))
        if self.local_artifact_sha256 is not None:
            if not isinstance(self.local_artifact_sha256, str):
                raise ContractValidationError("local_artifact_sha256 must be a string or null")
            _require_sha256(self.local_artifact_sha256, "local_artifact_sha256")
        if not hosted_identity and self.local_artifact_sha256 is None:
            raise ContractValidationError(
                "freeze provider/model/version or a local artifact SHA-256"
            )
        if not isinstance(self.system_prompt_bytes, bytes) or not isinstance(
            self.user_prompt_bytes, bytes
        ):
            raise ContractValidationError("system and user prompts must be exact bytes")

        if any(not isinstance(item, str) or not item for item in self.visible_input_fields):
            raise ContractValidationError("visible input field names must be non-empty strings")
        if any(not isinstance(item, str) or not item for item in self.hidden_input_fields):
            raise ContractValidationError("hidden input field names must be non-empty strings")
        visible = tuple(self.visible_input_fields)
        hidden = tuple(self.hidden_input_fields)
        if len(set(visible)) != len(visible) or len(set(hidden)) != len(hidden):
            raise ContractValidationError("visible/hidden input field names must be unique")
        if set(visible) & set(hidden):
            raise ContractValidationError("visible and hidden input fields must be disjoint")
        reserved = {self.candidate_text_field, self.economic_stance_field}
        if reserved & (set(visible) | set(hidden)) or len(reserved) != 2:
            raise ContractValidationError(
                "candidate text, economic stance, visible, and hidden fields must be separated"
            )
        if "treatment_arm" not in hidden:
            raise ContractValidationError("treatment_arm must be a frozen hidden input")
        object.__setattr__(self, "visible_input_fields", visible)
        object.__setattr__(self, "hidden_input_fields", hidden)

        seeds = tuple(self.receiver_seeds)
        if (
            not seeds
            or len(set(seeds)) != len(seeds)
            or any(not isinstance(seed, int) or isinstance(seed, bool) or seed < 0 for seed in seeds)
        ):
            raise ContractValidationError("receiver_seeds must be unique nonnegative integers")
        object.__setattr__(self, "receiver_seeds", seeds)
        if not isinstance(self.decoding_parameters, Mapping):
            raise ContractValidationError("decoding_parameters must be a JSON object")
        if not isinstance(self.output_schema, Mapping):
            raise ContractValidationError("output_schema must be a JSON object")
        if not isinstance(self.failure_actions, Mapping):
            raise ContractValidationError("failure_actions must be a JSON object")
        object.__setattr__(self, "decoding_parameters", _immutable_json(self.decoding_parameters))
        object.__setattr__(self, "output_schema", _immutable_json(self.output_schema))
        object.__setattr__(self, "failure_actions", _immutable_json(self.failure_actions))

        actions = _plain_json(self.failure_actions)
        if set(actions) != set(_FAILURE_KINDS) or any(
            action not in _FAILURE_ACTIONS for action in actions.values()
        ):
            raise ContractValidationError(
                f"failure_actions must freeze exactly {sorted(_FAILURE_KINDS)}"
            )
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ContractValidationError("max_attempts must be at least one")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ContractValidationError("timeout_seconds must be finite and positive")
        if self.missingness_rule != MISSINGNESS_RULE:
            raise ContractValidationError("missingness must retain prespecified failed rows")
        if self.cache_mode != CACHE_MODE:
            raise ContractValidationError("only exact envelope cache/replay is supported")
        caps = (
            self.max_calls,
            self.max_input_tokens,
            self.max_output_tokens,
            self.max_cost_microusd,
        )
        if any(not isinstance(cap, int) or isinstance(cap, bool) or cap < 0 for cap in caps) or self.max_calls == 0:
            raise ContractValidationError("call/token/cost caps must be nonnegative; calls must be positive")
        if (
            not isinstance(self.max_runtime_seconds, (int, float))
            or isinstance(self.max_runtime_seconds, bool)
            or not math.isfinite(self.max_runtime_seconds)
            or self.max_runtime_seconds < self.timeout_seconds
        ):
            raise ContractValidationError("runtime cap must be finite and at least one timeout")
        selection_values = (
            self.receiver_selection_is_treatment_blind,
            self.selection_frozen_before_treatment,
            self.selection_uses_factorial_payoff,
            self.selection_uses_treatment_templates,
        )
        if any(type(value) is not bool for value in selection_values) or selection_values != (
            True,
            True,
            False,
            False,
        ):
            raise ContractValidationError(
                "receiver selection must be prospectively frozen, treatment-blind, and use "
                "neither factorial payoff nor treatment templates"
            )
        if self.parser_id != "strict_json_decision_v1":
            raise ContractValidationError("unsupported output parser")
        decisions = tuple(self.allowed_decisions)
        refusals = tuple(self.refusal_decisions)
        if any(not isinstance(item, str) or not item for item in decisions + refusals):
            raise ContractValidationError("decision values must be non-empty strings")
        object.__setattr__(self, "allowed_decisions", decisions)
        object.__setattr__(self, "refusal_decisions", refusals)
        self._validate_output_schema()

    def _validate_output_schema(self) -> None:
        schema = _plain_json(self.output_schema)
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or not isinstance(schema.get("properties"), dict)
            or not isinstance(schema.get("required"), list)
            or self.decision_field not in schema["required"]
        ):
            raise ContractValidationError("output_schema must be a strict JSON object schema")
        decision = schema["properties"].get(self.decision_field)
        values = tuple(self.allowed_decisions) + tuple(self.refusal_decisions)
        if (
            not isinstance(decision, dict)
            or decision.get("type") != "string"
            or tuple(decision.get("enum") or ()) != values
            or not self.allowed_decisions
            or not self.refusal_decisions
            or len(set(values)) != len(values)
        ):
            raise ContractValidationError(
                "decision schema enum must equal allowed_decisions then refusal_decisions"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_id": self.contract_id,
            "receiver_identity": {
                "provider": self.provider,
                "model": self.model,
                "version": self.version,
                "local_artifact_sha256": self.local_artifact_sha256,
            },
            "prompts": {
                "system_prompt_b64": _b64(self.system_prompt_bytes),
                "user_prompt_b64": _b64(self.user_prompt_bytes),
            },
            "input_contract": {
                "visible_input_fields": list(self.visible_input_fields),
                "hidden_input_fields": list(self.hidden_input_fields),
                "candidate_text_field": self.candidate_text_field,
                "economic_stance_field": self.economic_stance_field,
            },
            "decoding_parameters": _plain_json(self.decoding_parameters),
            "receiver_seeds": list(self.receiver_seeds),
            "output_contract": {
                "parser_id": self.parser_id,
                "schema": _plain_json(self.output_schema),
                "decision_field": self.decision_field,
                "allowed_decisions": list(self.allowed_decisions),
                "refusal_decisions": list(self.refusal_decisions),
            },
            "failure_contract": {
                "actions": _plain_json(self.failure_actions),
                "max_attempts": self.max_attempts,
                "timeout_seconds": self.timeout_seconds,
                "missingness_rule": self.missingness_rule,
            },
            "cache_mode": self.cache_mode,
            "caps": {
                "max_calls": self.max_calls,
                "max_input_tokens": self.max_input_tokens,
                "max_output_tokens": self.max_output_tokens,
                "max_cost_microusd": self.max_cost_microusd,
                "max_runtime_seconds": self.max_runtime_seconds,
            },
            "eligibility": {
                "family": self.eligible_family,
                "candidate_role": self.eligible_candidate_role,
                "receiver_role": self.receiver_role,
            },
            "selection": {
                "rule": self.receiver_selection_rule,
                "treatment_blind": self.receiver_selection_is_treatment_blind,
                "frozen_before_treatment": self.selection_frozen_before_treatment,
                "uses_factorial_payoff": self.selection_uses_factorial_payoff,
                "uses_treatment_templates": self.selection_uses_treatment_templates,
            },
        }

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.to_dict()))

    @property
    def parser_and_failure_sha256(self) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "output_contract": self.to_dict()["output_contract"],
                    "failure_contract": self.to_dict()["failure_contract"],
                }
            )
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReceiverContract":
        if value.get("schema") != CONTRACT_SCHEMA:
            raise ContractValidationError("receiver contract schema mismatch")
        identity = value["receiver_identity"]
        prompts = value["prompts"]
        inputs = value["input_contract"]
        output = value["output_contract"]
        failure = value["failure_contract"]
        caps = value["caps"]
        eligibility = value["eligibility"]
        selection = value["selection"]
        try:
            return cls(
                contract_id=str(value["contract_id"]),
                provider=str(identity["provider"]),
                model=str(identity["model"]),
                version=str(identity["version"]),
                local_artifact_sha256=identity.get("local_artifact_sha256"),
                system_prompt_bytes=_unb64(str(prompts["system_prompt_b64"])),
                user_prompt_bytes=_unb64(str(prompts["user_prompt_b64"])),
                visible_input_fields=tuple(inputs["visible_input_fields"]),
                hidden_input_fields=tuple(inputs["hidden_input_fields"]),
                candidate_text_field=str(inputs["candidate_text_field"]),
                economic_stance_field=str(inputs["economic_stance_field"]),
                decoding_parameters=value["decoding_parameters"],
                receiver_seeds=tuple(value["receiver_seeds"]),
                parser_id=str(output["parser_id"]),
                output_schema=output["schema"],
                decision_field=str(output["decision_field"]),
                allowed_decisions=tuple(output["allowed_decisions"]),
                refusal_decisions=tuple(output["refusal_decisions"]),
                failure_actions=failure["actions"],
                max_attempts=int(failure["max_attempts"]),
                timeout_seconds=float(failure["timeout_seconds"]),
                missingness_rule=str(failure["missingness_rule"]),
                cache_mode=str(value["cache_mode"]),
                max_calls=int(caps["max_calls"]),
                max_input_tokens=int(caps["max_input_tokens"]),
                max_output_tokens=int(caps["max_output_tokens"]),
                max_cost_microusd=int(caps["max_cost_microusd"]),
                max_runtime_seconds=float(caps["max_runtime_seconds"]),
                eligible_family=str(eligibility["family"]),
                eligible_candidate_role=str(eligibility["candidate_role"]),
                receiver_role=str(eligibility["receiver_role"]),
                receiver_selection_rule=str(selection["rule"]),
                receiver_selection_is_treatment_blind=selection["treatment_blind"],
                selection_frozen_before_treatment=selection["frozen_before_treatment"],
                selection_uses_factorial_payoff=selection["uses_factorial_payoff"],
                selection_uses_treatment_templates=selection["uses_treatment_templates"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("receiver contract document is malformed") from exc


@dataclass(frozen=True)
class RequestEnvelope:
    contract_sha256: str
    probe_id: str
    outbound_bytes: bytes
    outbound_sha256: str
    hidden_inputs_sha256: str
    hidden_input_fields: tuple[str, ...]
    request_sha256: str
    schema: str = field(default=REQUEST_SCHEMA, init=False)

    @classmethod
    def build(
        cls,
        contract: ReceiverContract,
        *,
        probe_id: str,
        candidate_text: str,
        economic_stance: Mapping[str, Any],
        visible_inputs: Mapping[str, Any],
        hidden_inputs: Mapping[str, Any],
        seed: int,
    ) -> "RequestEnvelope":
        if not probe_id:
            raise EnvelopeIntegrityError("probe_id must be non-empty")
        if not isinstance(candidate_text, str):
            raise EnvelopeIntegrityError("candidate text must be a string")
        if set(visible_inputs) != set(contract.visible_input_fields):
            raise EnvelopeIntegrityError("visible input keys do not match the frozen contract")
        if set(hidden_inputs) != set(contract.hidden_input_fields):
            raise EnvelopeIntegrityError("hidden input keys do not match the frozen contract")
        if seed not in contract.receiver_seeds:
            raise EnvelopeIntegrityError("receiver seed is not frozen in the contract")
        outbound = {
            "schema": REQUEST_SCHEMA,
            "contract_sha256": contract.sha256,
            "receiver_identity": contract.to_dict()["receiver_identity"],
            "system_prompt_b64": _b64(contract.system_prompt_bytes),
            "user_prompt_b64": _b64(contract.user_prompt_bytes),
            "decoding_parameters": _plain_json(contract.decoding_parameters),
            "seed": seed,
            "inputs": {
                contract.economic_stance_field: _plain_json(economic_stance),
                contract.candidate_text_field: candidate_text,
                "visible": _plain_json(visible_inputs),
            },
        }
        outbound_bytes = canonical_json_bytes(outbound)
        outbound_sha = sha256_hex(outbound_bytes)
        hidden_sha = sha256_hex(canonical_json_bytes(hidden_inputs))
        unsigned = {
            "schema": REQUEST_SCHEMA,
            "contract_sha256": contract.sha256,
            "probe_id": probe_id,
            "outbound_b64": _b64(outbound_bytes),
            "outbound_sha256": outbound_sha,
            "hidden_inputs_sha256": hidden_sha,
            "hidden_input_fields": list(contract.hidden_input_fields),
        }
        return cls(
            contract_sha256=contract.sha256,
            probe_id=probe_id,
            outbound_bytes=outbound_bytes,
            outbound_sha256=outbound_sha,
            hidden_inputs_sha256=hidden_sha,
            hidden_input_fields=contract.hidden_input_fields,
            request_sha256=sha256_hex(canonical_json_bytes(unsigned)),
        )

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_sha256": self.contract_sha256,
            "probe_id": self.probe_id,
            "outbound_b64": _b64(self.outbound_bytes),
            "outbound_sha256": self.outbound_sha256,
            "hidden_inputs_sha256": self.hidden_inputs_sha256,
            "hidden_input_fields": list(self.hidden_input_fields),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "request_sha256": self.request_sha256}

    def verify(self, contract: ReceiverContract | None = None) -> None:
        if sha256_hex(self.outbound_bytes) != self.outbound_sha256:
            raise EnvelopeIntegrityError("outbound request hash mismatch")
        if sha256_hex(canonical_json_bytes(self.unsigned_dict())) != self.request_sha256:
            raise EnvelopeIntegrityError("request envelope hash mismatch")
        if contract is not None:
            if self.contract_sha256 != contract.sha256:
                raise EnvelopeIntegrityError("request does not bind the supplied receiver contract")
            if tuple(self.hidden_input_fields) != tuple(contract.hidden_input_fields):
                raise EnvelopeIntegrityError("request hidden-field commitment changed")
            outbound = self.outbound_object()
            expected_top_level = {
                "schema",
                "contract_sha256",
                "receiver_identity",
                "system_prompt_b64",
                "user_prompt_b64",
                "decoding_parameters",
                "seed",
                "inputs",
            }
            if set(outbound) != expected_top_level:
                raise EnvelopeIntegrityError("outbound receiver fields differ from the contract")
            expected_static = {
                "schema": REQUEST_SCHEMA,
                "contract_sha256": contract.sha256,
                "receiver_identity": contract.to_dict()["receiver_identity"],
                "system_prompt_b64": _b64(contract.system_prompt_bytes),
                "user_prompt_b64": _b64(contract.user_prompt_bytes),
                "decoding_parameters": _plain_json(contract.decoding_parameters),
            }
            if any(outbound.get(key) != value for key, value in expected_static.items()):
                raise EnvelopeIntegrityError("outbound receiver contract bytes changed")
            if outbound.get("seed") not in contract.receiver_seeds:
                raise EnvelopeIntegrityError("outbound receiver seed is not frozen")
            inputs = outbound.get("inputs")
            if not isinstance(inputs, Mapping) or set(inputs) != {
                contract.economic_stance_field,
                contract.candidate_text_field,
                "visible",
            }:
                raise EnvelopeIntegrityError("outbound input fields differ from the contract")
            if not isinstance(inputs.get(contract.economic_stance_field), Mapping):
                raise EnvelopeIntegrityError("economic stance must be a JSON object")
            if not isinstance(inputs.get(contract.candidate_text_field), str):
                raise EnvelopeIntegrityError("candidate text must be a string")
            visible = inputs.get("visible")
            if not isinstance(visible, Mapping) or set(visible) != set(
                contract.visible_input_fields
            ):
                raise EnvelopeIntegrityError("outbound visible fields differ from the contract")
            if any(_contains_mapping_key(outbound, key) for key in contract.hidden_input_fields):
                raise EnvelopeIntegrityError("hidden input field leaked into outbound bytes")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequestEnvelope":
        if value.get("schema") != REQUEST_SCHEMA:
            raise EnvelopeIntegrityError("request schema mismatch")
        result = cls(
            contract_sha256=str(value["contract_sha256"]),
            probe_id=str(value["probe_id"]),
            outbound_bytes=_unb64(str(value["outbound_b64"])),
            outbound_sha256=str(value["outbound_sha256"]),
            hidden_inputs_sha256=str(value["hidden_inputs_sha256"]),
            hidden_input_fields=tuple(value["hidden_input_fields"]),
            request_sha256=str(value["request_sha256"]),
        )
        result.verify()
        return result

    def outbound_object(self) -> dict[str, Any]:
        try:
            value = json.loads(self.outbound_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnvelopeIntegrityError("outbound request is not canonical JSON") from exc
        if canonical_json_bytes(value) != self.outbound_bytes:
            raise EnvelopeIntegrityError("outbound request bytes are not canonical")
        return value


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or value < 0
            for value in (self.input_tokens, self.output_tokens, self.cost_microusd)
        ):
            raise ValueError("usage must contain nonnegative integers")

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microusd": self.cost_microusd,
        }


@dataclass(frozen=True)
class TransportResult:
    response_bytes: bytes
    usage: Usage = field(default_factory=Usage)
    elapsed_ms: int = 0
    transport_status: str = "ok"
    consumed_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.response_bytes, bytes):
            raise TypeError("transport response must be exact bytes")
        if self.elapsed_ms < 0 or self.transport_status not in {"ok", "timeout"}:
            raise ValueError("invalid transport result")
        if self.transport_status == "timeout" and self.response_bytes:
            raise ValueError("a timeout cannot also contain response bytes")


ReceiverTransport = Callable[[bytes, float], TransportResult]


@dataclass(frozen=True)
class ResponseEnvelope:
    request_sha256: str
    attempt: int
    response_bytes: bytes
    response_sha256: str
    usage: Usage
    elapsed_ms: int
    transport_status: str
    consumed_fields: tuple[str, ...]
    response_envelope_sha256: str
    schema: str = field(default=RESPONSE_SCHEMA, init=False)

    @classmethod
    def build(
        cls, request: RequestEnvelope, attempt: int, result: TransportResult
    ) -> "ResponseEnvelope":
        unsigned = {
            "schema": RESPONSE_SCHEMA,
            "request_sha256": request.request_sha256,
            "attempt": attempt,
            "response_b64": _b64(result.response_bytes),
            "response_sha256": sha256_hex(result.response_bytes),
            "usage": result.usage.to_dict(),
            "elapsed_ms": result.elapsed_ms,
            "transport_status": result.transport_status,
            "consumed_fields": list(result.consumed_fields),
        }
        return cls(
            request_sha256=request.request_sha256,
            attempt=attempt,
            response_bytes=result.response_bytes,
            response_sha256=unsigned["response_sha256"],
            usage=result.usage,
            elapsed_ms=result.elapsed_ms,
            transport_status=result.transport_status,
            consumed_fields=tuple(result.consumed_fields),
            response_envelope_sha256=sha256_hex(canonical_json_bytes(unsigned)),
        )

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_sha256": self.request_sha256,
            "attempt": self.attempt,
            "response_b64": _b64(self.response_bytes),
            "response_sha256": self.response_sha256,
            "usage": self.usage.to_dict(),
            "elapsed_ms": self.elapsed_ms,
            "transport_status": self.transport_status,
            "consumed_fields": list(self.consumed_fields),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.unsigned_dict(),
            "response_envelope_sha256": self.response_envelope_sha256,
        }

    def verify(self, request: RequestEnvelope) -> None:
        if self.request_sha256 != request.request_sha256:
            raise EnvelopeIntegrityError("response is bound to a different request")
        if sha256_hex(self.response_bytes) != self.response_sha256:
            raise EnvelopeIntegrityError("response bytes hash mismatch")
        if sha256_hex(canonical_json_bytes(self.unsigned_dict())) != self.response_envelope_sha256:
            raise EnvelopeIntegrityError("response envelope hash mismatch")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], request: RequestEnvelope) -> "ResponseEnvelope":
        if value.get("schema") != RESPONSE_SCHEMA:
            raise EnvelopeIntegrityError("response schema mismatch")
        usage = value["usage"]
        result = cls(
            request_sha256=str(value["request_sha256"]),
            attempt=int(value["attempt"]),
            response_bytes=_unb64(str(value["response_b64"])),
            response_sha256=str(value["response_sha256"]),
            usage=Usage(
                input_tokens=int(usage["input_tokens"]),
                output_tokens=int(usage["output_tokens"]),
                cost_microusd=int(usage["cost_microusd"]),
            ),
            elapsed_ms=int(value["elapsed_ms"]),
            transport_status=str(value["transport_status"]),
            consumed_fields=tuple(value["consumed_fields"]),
            response_envelope_sha256=str(value["response_envelope_sha256"]),
        )
        result.verify(request)
        return result


@dataclass(frozen=True)
class ParsedOutput:
    status: str
    decision: str | None
    failure_kind: str | None


class StrictJSONDecisionParser:
    def __init__(self, contract: ReceiverContract) -> None:
        self.contract = contract

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        return {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "null": value is None,
        }.get(expected, False)

    def parse(self, response: ResponseEnvelope) -> ParsedOutput:
        if response.transport_status == "timeout":
            return ParsedOutput("failure", None, "timeout")
        if not response.response_bytes.strip():
            return ParsedOutput("failure", None, "missing")
        try:
            value = json.loads(response.response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ParsedOutput("failure", None, "malformed")
        schema = _plain_json(self.contract.output_schema)
        if not isinstance(value, dict):
            return ParsedOutput("failure", None, "malformed")
        properties = schema["properties"]
        if any(key not in properties for key in value):
            return ParsedOutput("failure", None, "malformed")
        if any(key not in value for key in schema["required"]):
            return ParsedOutput("failure", None, "malformed")
        for key, item in value.items():
            rule = properties[key]
            if not self._matches_type(item, rule.get("type")):
                return ParsedOutput("failure", None, "malformed")
            if "enum" in rule and item not in rule["enum"]:
                return ParsedOutput("failure", None, "malformed")
        decision = value[self.contract.decision_field]
        if decision in self.contract.refusal_decisions:
            return ParsedOutput("failure", None, "refusal")
        if decision not in self.contract.allowed_decisions:
            return ParsedOutput("failure", None, "malformed")
        return ParsedOutput("ok", decision, None)


@dataclass(frozen=True)
class ReceiverObservation:
    status: str
    decision: str | None
    failure_kind: str | None
    attempts: int
    missing: bool
    evidence_label: str = INFRASTRUCTURE_ONLY_NON_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CacheRecord:
    request: RequestEnvelope
    responses: tuple[ResponseEnvelope, ...]
    observation: ReceiverObservation

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "responses": [response.to_dict() for response in self.responses],
            "observation": self.observation.to_dict(),
        }

    @property
    def record_sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "record_sha256": self.record_sha256}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def verify(self) -> None:
        self.request.verify()
        for index, response in enumerate(self.responses, start=1):
            response.verify(self.request)
            if response.attempt != index:
                raise EnvelopeIntegrityError("response attempt sequence is not contiguous")
        if self.observation.attempts != len(self.responses):
            raise EnvelopeIntegrityError("observation attempt count mismatch")
        if self.observation.evidence_label != INFRASTRUCTURE_ONLY_NON_EVIDENCE:
            raise EnvelopeIntegrityError("receiver infrastructure result has an invalid evidence label")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CacheRecord":
        request = RequestEnvelope.from_dict(value["request"])
        responses = tuple(ResponseEnvelope.from_dict(item, request) for item in value["responses"])
        observation = ReceiverObservation(**value["observation"])
        result = cls(request, responses, observation)
        result.verify()
        if value.get("record_sha256") != result.record_sha256:
            raise EnvelopeIntegrityError("cache record hash mismatch")
        return result


class ExactReplayCache:
    def __init__(self) -> None:
        self._records: dict[str, CacheRecord] = {}

    def put(self, record: CacheRecord) -> None:
        record.verify()
        key = record.request.request_sha256
        previous = self._records.get(key)
        if previous is not None and previous.to_bytes() != record.to_bytes():
            raise EnvelopeIntegrityError("refusing conflicting response for an exact request")
        self._records[key] = record

    def get(self, request: RequestEnvelope) -> CacheRecord | None:
        request.verify()
        result = self._records.get(request.request_sha256)
        if result is not None and result.request.to_dict() != request.to_dict():
            raise EnvelopeIntegrityError("cache key collision for nonidentical request envelopes")
        return result

    def dump_bytes(self) -> bytes:
        unsigned = {
            "schema": CACHE_SCHEMA,
            "evidence_label": INFRASTRUCTURE_ONLY_NON_EVIDENCE,
            "records": [self._records[key].to_dict() for key in sorted(self._records)],
        }
        return canonical_json_bytes(
            {**unsigned, "cache_sha256": sha256_hex(canonical_json_bytes(unsigned))}
        )

    @classmethod
    def load_bytes(cls, data: bytes) -> "ExactReplayCache":
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnvelopeIntegrityError("cache is not JSON") from exc
        if canonical_json_bytes(value) != data or value.get("schema") != CACHE_SCHEMA:
            raise EnvelopeIntegrityError("cache is noncanonical or has the wrong schema")
        if value.get("evidence_label") != INFRASTRUCTURE_ONLY_NON_EVIDENCE:
            raise EnvelopeIntegrityError("cache evidence label mismatch")
        unsigned = {key: item for key, item in value.items() if key != "cache_sha256"}
        if value.get("cache_sha256") != sha256_hex(canonical_json_bytes(unsigned)):
            raise EnvelopeIntegrityError("cache hash mismatch")
        result = cls()
        for item in value.get("records", []):
            result.put(CacheRecord.from_dict(item))
        return result


@dataclass(frozen=True)
class CallReservation:
    input_tokens: int
    max_output_tokens: int
    max_cost_microusd: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or value < 0
            for value in (self.input_tokens, self.max_output_tokens, self.max_cost_microusd)
        ):
            raise ValueError("call reservation values must be nonnegative integers")


@dataclass
class BudgetLedger:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microusd: int = 0
    runtime_ms: int = 0

    def reserve(self, contract: ReceiverContract, reservation: CallReservation) -> None:
        proposed = (
            self.calls + 1,
            self.input_tokens + reservation.input_tokens,
            self.output_tokens + reservation.max_output_tokens,
            self.cost_microusd + reservation.max_cost_microusd,
        )
        caps = (
            contract.max_calls,
            contract.max_input_tokens,
            contract.max_output_tokens,
            contract.max_cost_microusd,
        )
        if any(value > cap for value, cap in zip(proposed, caps)):
            raise BudgetExceeded("call reservation would exceed the frozen receiver caps")
        if self.runtime_ms / 1000.0 >= contract.max_runtime_seconds:
            raise BudgetExceeded("receiver runtime cap is exhausted")

    def charge(
        self,
        contract: ReceiverContract,
        reservation: CallReservation,
        result: TransportResult,
    ) -> None:
        if (
            result.usage.input_tokens > reservation.input_tokens
            or result.usage.output_tokens > reservation.max_output_tokens
            or result.usage.cost_microusd > reservation.max_cost_microusd
        ):
            raise BudgetExceeded("transport usage exceeded its preauthorized reservation")
        self.calls += 1
        self.input_tokens += result.usage.input_tokens
        self.output_tokens += result.usage.output_tokens
        self.cost_microusd += result.usage.cost_microusd
        self.runtime_ms += result.elapsed_ms
        if self.runtime_ms / 1000.0 > contract.max_runtime_seconds:
            raise BudgetExceeded("receiver runtime exceeded the frozen cap")


@dataclass(frozen=True)
class InvocationResult:
    record: CacheRecord
    cache_hit: bool


class ControlledReceiverHarness:
    def __init__(self, contract: ReceiverContract, cache: ExactReplayCache | None = None) -> None:
        self.contract = contract
        self.cache = cache if cache is not None else ExactReplayCache()
        self.parser = StrictJSONDecisionParser(contract)
        self.budget = BudgetLedger()

    def invoke(
        self,
        request: RequestEnvelope,
        *,
        reservation: CallReservation,
        transport: ReceiverTransport | None = None,
        replay_only: bool = False,
    ) -> InvocationResult:
        request.verify(self.contract)
        cached = self.cache.get(request)
        if cached is not None:
            return InvocationResult(cached, True)
        if replay_only:
            raise CacheMiss(f"no exact cache record for {request.request_sha256}")
        if transport is None:
            raise ControlledReceiverError("cache miss requires an explicitly injected transport")

        responses: list[ResponseEnvelope] = []
        final = ParsedOutput("failure", None, "missing")
        for attempt in range(1, self.contract.max_attempts + 1):
            self.budget.reserve(self.contract, reservation)
            started = time.monotonic()
            try:
                transport_result = transport(request.outbound_bytes, self.contract.timeout_seconds)
            except TimeoutError:
                elapsed = max(0, int((time.monotonic() - started) * 1000))
                transport_result = TransportResult(
                    b"", elapsed_ms=elapsed, transport_status="timeout"
                )
            self.budget.charge(self.contract, reservation, transport_result)
            response = ResponseEnvelope.build(request, attempt, transport_result)
            responses.append(response)
            final = self.parser.parse(response)
            if final.status == "ok":
                break
            action = self.contract.failure_actions[final.failure_kind]
            if action != "retry_then_record_missing" or attempt == self.contract.max_attempts:
                break

        observation = ReceiverObservation(
            status=final.status,
            decision=final.decision,
            failure_kind=final.failure_kind,
            attempts=len(responses),
            missing=final.status != "ok",
        )
        record = CacheRecord(request, tuple(responses), observation)
        self.cache.put(record)
        return InvocationResult(record, False)


@dataclass(frozen=True)
class CapabilityProbe:
    probe_id: str
    candidate_text_a: str
    candidate_text_b: str
    economic_stance: Mapping[str, Any]
    visible_inputs: Mapping[str, Any]
    hidden_inputs: Mapping[str, Any]
    seed: int

    def __post_init__(self) -> None:
        if not self.probe_id or self.candidate_text_a == self.candidate_text_b:
            raise ContractValidationError("capability probe needs an id and two different texts")
        for text in (self.candidate_text_a, self.candidate_text_b):
            if sha256_hex(text.encode("utf-8")) in _TREATMENT_TEMPLATE_SHA256:
                raise ContractValidationError(
                    "factorial treatment templates are prohibited in capability certification"
                )
        object.__setattr__(self, "economic_stance", _immutable_json(self.economic_stance))
        object.__setattr__(self, "visible_inputs", _immutable_json(self.visible_inputs))
        object.__setattr__(self, "hidden_inputs", _immutable_json(self.hidden_inputs))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityProbe":
        try:
            return cls(
                probe_id=str(value["probe_id"]),
                candidate_text_a=str(value["candidate_text_a"]),
                candidate_text_b=str(value["candidate_text_b"]),
                economic_stance=value["economic_stance"],
                visible_inputs=value["visible_inputs"],
                hidden_inputs=value["hidden_inputs"],
                seed=int(value["seed"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("capability probe document is malformed") from exc


def _contains_key_or_value(value: Any, key: str, hidden_value: Any) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key_or_value(item, key, hidden_value) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key_or_value(item, key, hidden_value) for item in value)
    return value == hidden_value


def _text_only_pair(
    first: RequestEnvelope, second: RequestEnvelope, contract: ReceiverContract
) -> bool:
    left = first.outbound_object()
    right = second.outbound_object()
    left_text = left["inputs"].pop(contract.candidate_text_field, None)
    right_text = right["inputs"].pop(contract.candidate_text_field, None)
    return left_text != right_text and left == right


def _failure_handling_arm_canary(
    contract: ReceiverContract, probe: CapabilityProbe
) -> bool:
    hidden_left = _plain_json(probe.hidden_inputs)
    hidden_right = _plain_json(probe.hidden_inputs)
    hidden_left["treatment_arm"] = "HIDDEN_CANARY_CAPABILITY_ARM_00"
    hidden_right["treatment_arm"] = "HIDDEN_CANARY_CAPABILITY_ARM_11"
    requests = tuple(
        RequestEnvelope.build(
            contract,
            probe_id=f"{probe.probe_id}:failure-arm-canary",
            candidate_text=probe.candidate_text_a,
            economic_stance=probe.economic_stance,
            visible_inputs=probe.visible_inputs,
            hidden_inputs=hidden,
            seed=probe.seed,
        )
        for hidden in (hidden_left, hidden_right)
    )
    if requests[0].outbound_bytes != requests[1].outbound_bytes:
        return False
    parser = StrictJSONDecisionParser(contract)
    cases = (
        ("timeout", TransportResult(b"", transport_status="timeout")),
        (
            "refusal",
            TransportResult(
                canonical_json_bytes(
                    {contract.decision_field: contract.refusal_decisions[0]}
                )
            ),
        ),
        ("malformed", TransportResult(b"{")),
        ("missing", TransportResult(b"")),
    )
    for expected, transport_result in cases:
        parsed = tuple(
            parser.parse(ResponseEnvelope.build(request, 1, transport_result))
            for request in requests
        )
        if parsed[0] != parsed[1] or parsed[0].failure_kind != expected:
            return False
    return True


@dataclass(frozen=True)
class CapabilityCertificate:
    contract_sha256: str
    probe_set_sha256: str
    candidate_text_delivered: bool
    receiver_consumes_candidate_text: bool
    text_only_perturbation_changes_output: bool
    hidden_treatment_information_not_exposed: bool
    parsing_and_failures_arm_invariant: bool
    exact_cache_replay: bool
    passed: bool
    probe_results: tuple[Mapping[str, Any], ...]
    parser_and_failure_sha256: str
    evidence_label: str = INFRASTRUCTURE_ONLY_NON_EVIDENCE
    schema: str = field(default=CERTIFICATE_SCHEMA, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "contract_sha256": self.contract_sha256,
            "probe_set_sha256": self.probe_set_sha256,
            "checks": {
                "candidate_text_delivered": self.candidate_text_delivered,
                "receiver_consumes_candidate_text": self.receiver_consumes_candidate_text,
                "text_only_perturbation_changes_output": self.text_only_perturbation_changes_output,
                "hidden_treatment_information_not_exposed": self.hidden_treatment_information_not_exposed,
                "parsing_and_failures_arm_invariant": self.parsing_and_failures_arm_invariant,
                "exact_cache_replay": self.exact_cache_replay,
            },
            "passed": self.passed,
            "probe_results": [_plain_json(item) for item in self.probe_results],
            "parser_and_failure_sha256": self.parser_and_failure_sha256,
            "evidence_label": self.evidence_label,
        }

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json_bytes(self.to_dict()))


def certify_capability(
    contract: ReceiverContract,
    probes: Sequence[CapabilityProbe],
    *,
    transport: ReceiverTransport,
    reservation: CallReservation,
    cache: ExactReplayCache | None = None,
) -> CapabilityCertificate:
    """Run generic, non-treatment capability probes through an injected transport."""

    if not probes:
        raise ContractValidationError("at least one prespecified capability probe is required")
    harness = ControlledReceiverHarness(contract, cache)
    delivered: list[bool] = []
    consumed: list[bool] = []
    perturbed: list[bool] = []
    hidden_safe: list[bool] = []
    replayed: list[bool] = []
    text_only: list[bool] = []
    failure_arm_invariant: list[bool] = []
    probe_results: list[Mapping[str, Any]] = []

    for probe in probes:
        requests = tuple(
            RequestEnvelope.build(
                contract,
                probe_id=f"{probe.probe_id}:{suffix}",
                candidate_text=text,
                economic_stance=probe.economic_stance,
                visible_inputs=probe.visible_inputs,
                hidden_inputs=probe.hidden_inputs,
                seed=probe.seed,
            )
            for suffix, text in (
                ("generic_text_a", probe.candidate_text_a),
                ("generic_text_b", probe.candidate_text_b),
            )
        )
        results = tuple(
            harness.invoke(request, reservation=reservation, transport=transport)
            for request in requests
        )
        objects = tuple(request.outbound_object() for request in requests)
        delivered_here = all(
            obj["inputs"].get(contract.candidate_text_field) == text
            for obj, text in zip(objects, (probe.candidate_text_a, probe.candidate_text_b))
        )
        delivered.append(delivered_here)
        final_responses = tuple(result.record.responses[-1] for result in results)
        consumed_here = all(
            contract.candidate_text_field in response.consumed_fields
            for response in final_responses
        )
        consumed.append(consumed_here)
        decisions = tuple(result.record.observation.decision for result in results)
        perturbed_here = (
            all(result.record.observation.status == "ok" for result in results)
            and decisions[0] != decisions[1]
        )
        perturbed.append(perturbed_here)
        safe_here = True
        for obj in objects:
            for key, hidden_value in probe.hidden_inputs.items():
                if _contains_key_or_value(obj, key, _plain_json(hidden_value)):
                    safe_here = False
        hidden_safe.append(safe_here)
        text_only_here = _text_only_pair(requests[0], requests[1], contract)
        text_only.append(text_only_here)
        failure_arm_invariant_here = _failure_handling_arm_canary(contract, probe)
        failure_arm_invariant.append(failure_arm_invariant_here)
        replay_here = True
        for request, original in zip(requests, results):
            replay = harness.invoke(request, reservation=reservation, replay_only=True)
            replay_here = replay_here and replay.cache_hit and (
                replay.record.to_bytes() == original.record.to_bytes()
            )
        replayed.append(replay_here)
        probe_results.append(
            {
                "probe_id": probe.probe_id,
                "request_sha256": [request.request_sha256 for request in requests],
                "outbound_sha256": [request.outbound_sha256 for request in requests],
                "status": [result.record.observation.status for result in results],
                "decision": list(decisions),
                "candidate_text_delivered": delivered_here,
                "receiver_consumes_candidate_text": consumed_here,
                "text_only_pair": text_only_here,
                "failure_handling_arm_canary": failure_arm_invariant_here,
                "output_changed": perturbed_here,
                "hidden_information_not_exposed": safe_here,
                "exact_cache_replay": replay_here,
                "evidence_label": INFRASTRUCTURE_ONLY_NON_EVIDENCE,
            }
        )

    checks = {
        "candidate_text_delivered": all(delivered),
        "receiver_consumes_candidate_text": all(consumed),
        "text_only_perturbation_changes_output": any(perturbed),
        "hidden_treatment_information_not_exposed": all(hidden_safe),
        "parsing_and_failures_arm_invariant": all(text_only)
        and all(failure_arm_invariant)
        and "treatment_arm" in contract.hidden_input_fields,
        "exact_cache_replay": all(replayed),
    }
    probe_set = [
        {
            "probe_id": probe.probe_id,
            "candidate_text_sha256": [
                sha256_hex(probe.candidate_text_a.encode("utf-8")),
                sha256_hex(probe.candidate_text_b.encode("utf-8")),
            ],
            "economic_stance": _plain_json(probe.economic_stance),
            "visible_inputs": _plain_json(probe.visible_inputs),
            "hidden_inputs_sha256": sha256_hex(canonical_json_bytes(probe.hidden_inputs)),
            "seed": probe.seed,
        }
        for probe in probes
    ]
    return CapabilityCertificate(
        contract_sha256=contract.sha256,
        probe_set_sha256=sha256_hex(canonical_json_bytes(probe_set)),
        passed=all(checks.values()),
        probe_results=tuple(probe_results),
        parser_and_failure_sha256=contract.parser_and_failure_sha256,
        **checks,
    )


def _load_transport(specification: str) -> ReceiverTransport:
    if specification.count(":") != 1:
        raise ControlledReceiverError("transport must use module.path:callable_name syntax")
    module_name, attribute = specification.split(":", 1)
    try:
        transport = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ControlledReceiverError(f"cannot load receiver transport {specification}") from exc
    if not callable(transport):
        raise ControlledReceiverError("selected receiver transport is not callable")
    return transport


def main(argv: Sequence[str] | None = None) -> int:
    """Run a later authorized certificate using a separately supplied adapter.

    The CLI deliberately has no built-in provider client.  The transport named
    on the command line is the authorization boundary and must implement the
    two-argument ``ReceiverTransport`` protocol.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("certify", choices=("certify",))
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--probes", required=True, type=Path)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--cache-out", required=True, type=Path)
    parser.add_argument("--certificate-out", required=True, type=Path)
    parser.add_argument("--reserved-input-tokens", required=True, type=int)
    parser.add_argument("--reserved-output-tokens", required=True, type=int)
    parser.add_argument("--reserved-cost-microusd", required=True, type=int)
    args = parser.parse_args(argv)

    try:
        contract_document = json.loads(args.contract.read_text(encoding="utf-8"))
        probe_document = json.loads(args.probes.read_text(encoding="utf-8"))
        contract = ReceiverContract.from_dict(contract_document)
        if probe_document.get("schema") != "glee.research.receiver_capability_probes.v1":
            raise ContractValidationError("capability probe-set schema mismatch")
        probes = tuple(CapabilityProbe.from_dict(item) for item in probe_document["probes"])
        cache = ExactReplayCache()
        certificate = certify_capability(
            contract,
            probes,
            transport=_load_transport(args.transport),
            reservation=CallReservation(
                input_tokens=args.reserved_input_tokens,
                max_output_tokens=args.reserved_output_tokens,
                max_cost_microusd=args.reserved_cost_microusd,
            ),
            cache=cache,
        )
        args.cache_out.write_bytes(cache.dump_bytes())
        args.certificate_out.write_bytes(canonical_json_bytes(certificate.to_dict()))
    except (ControlledReceiverError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"controlled receiver certification failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "certificate_sha256": certificate.sha256,
                "contract_sha256": contract.sha256,
                "passed": certificate.passed,
                "evidence_label": certificate.evidence_label,
            },
            sort_keys=True,
        )
    )
    return 0 if certificate.passed else 1


__all__ = [
    "BudgetExceeded",
    "CACHE_MODE",
    "CallReservation",
    "CapabilityCertificate",
    "CapabilityProbe",
    "CacheMiss",
    "ContractValidationError",
    "ControlledReceiverError",
    "ControlledReceiverHarness",
    "EnvelopeIntegrityError",
    "ExactReplayCache",
    "INFRASTRUCTURE_ONLY_NON_EVIDENCE",
    "MISSINGNESS_RULE",
    "ReceiverContract",
    "RequestEnvelope",
    "TransportResult",
    "Usage",
    "canonical_json_bytes",
    "certify_capability",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
