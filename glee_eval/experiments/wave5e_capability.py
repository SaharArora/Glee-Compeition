"""Fail-closed 100-request GPT-4.1 receiver capability runner.

This module makes no call unless its CLI is explicitly invoked with a protected
key file and an independent audit-GO document matching the exact Git commit and
source hashes.  It has no fallback provider or model path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from glee_eval.experiments.controlled_receiver import (
    CallReservation,
    ControlledReceiverError,
    ExactReplayCache,
    canonical_json_bytes,
    certify_capability,
)
from glee_eval.experiments.openai_responses import (
    OpenAIAdapterError,
    OpenAIResponsesTransport,
    load_protected_api_key,
)
from glee_eval.experiments.wave5c_receiver import (
    build_capability_probes,
    build_receiver_contract,
    capability_rule_summary,
)


RUN_SCHEMA = "glee.research.wave5e.receiver_capability.v1"
AUDIT_GO_SCHEMA = "glee.research.wave5e.receiver_adapter_audit_go.v1"
NOMINAL_REQUESTS = 100
MAX_ATTEMPTS = 200
ROUTE_COST_CAP_MICROUSD = 1_000_000
RESERVATION = CallReservation(
    input_tokens=2048,
    max_output_tokens=16,
    max_cost_microusd=4_224,
)
PINNED_SOURCE_PATHS = (
    "glee_eval/experiments/controlled_receiver.py",
    "glee_eval/experiments/openai_responses.py",
    "glee_eval/experiments/receiver_itt.py",
    "glee_eval/experiments/wave5c_receiver.py",
    "glee_eval/experiments/wave5e_capability.py",
    "research/LOCKS/WAVE5E_OPENAI_ADAPTER_LOCK.json",
)


class CapabilityRunError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve(strict=True)
    output: dict[str, str] = {}
    for name in PINNED_SOURCE_PATHS:
        path = root / name
        if not path.is_file():
            raise CapabilityRunError(f"pinned adapter source is missing: {name}")
        output[name] = _sha256(path)
    return output


def _git_head(repository_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_independent_audit_go(
    audit: Mapping[str, Any], *, repository_root: str | Path
) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    expected_keys = {
        "schema",
        "verdict",
        "independent_auditor",
        "implementation_commit",
        "source_sha256",
        "automatic_fallback",
        "api_call_performed_by_audit",
    }
    if set(audit) != expected_keys or audit.get("schema") != AUDIT_GO_SCHEMA:
        raise CapabilityRunError("independent adapter audit document has the wrong schema")
    if audit.get("verdict") != "GO" or not str(audit.get("independent_auditor") or ""):
        raise CapabilityRunError("independent adapter audit did not issue GO")
    if audit.get("automatic_fallback") is not False:
        raise CapabilityRunError("independent adapter audit permits fallback")
    if audit.get("api_call_performed_by_audit") is not False:
        raise CapabilityRunError("adapter audit must be offline")
    head = _git_head(root)
    if audit.get("implementation_commit") != head:
        raise CapabilityRunError("independent adapter audit covers another Git commit")
    observed_hashes = audit.get("source_sha256")
    expected_hashes = source_hashes(root)
    if observed_hashes != expected_hashes:
        raise CapabilityRunError("independent adapter audit source hashes do not match")
    return {"implementation_commit": head, "source_sha256": expected_hashes}


def run_capability(transport: OpenAIResponsesTransport) -> dict[str, Any]:
    contract = build_receiver_contract()
    if transport.contract.sha256 != contract.sha256:
        raise CapabilityRunError("transport uses another receiver contract")
    probes = build_capability_probes()
    if len(probes) * 2 != NOMINAL_REQUESTS:
        raise CapabilityRunError("capability probe set no longer has exactly 100 requests")
    if MAX_ATTEMPTS * RESERVATION.max_cost_microusd > ROUTE_COST_CAP_MICROUSD:
        raise CapabilityRunError("pre-reservation arithmetic exceeds the $1 route cap")
    cache = ExactReplayCache()
    certificate = certify_capability(
        contract,
        probes,
        transport=transport,
        reservation=RESERVATION,
        cache=cache,
    )
    rule = capability_rule_summary(certificate)
    attempts = sum(len(item.responses) for item in cache._records.values())
    if attempts != certificate_request_attempts(cache) or attempts > MAX_ATTEMPTS:
        raise CapabilityRunError("capability attempts exceed or contradict the frozen ceiling")
    if cache._records.keys() and len(cache._records) != NOMINAL_REQUESTS:
        raise CapabilityRunError("capability did not retain exactly 100 nominal request records")
    if certificate.contract_sha256 != contract.sha256:
        raise CapabilityRunError("capability certificate is bound to another receiver contract")
    if certificate.evidence_label != "infrastructure_only_non_evidence":
        raise CapabilityRunError("capability certificate has an invalid evidence class")
    if transport.contract.max_attempts * NOMINAL_REQUESTS != MAX_ATTEMPTS:
        raise CapabilityRunError("receiver retry contract no longer implies 200 attempts maximum")
    actual_cost = sum(
        response.usage.cost_microusd
        for record in cache._records.values()
        for response in record.responses
    )
    if actual_cost > ROUTE_COST_CAP_MICROUSD:
        raise CapabilityRunError("capability route exceeded the $1 hard cost ceiling")
    passed = bool(certificate.passed and rule["passed"])
    return {
        "schema": RUN_SCHEMA,
        "status": "PASS" if passed else "FAIL",
        "receiver_contract_sha256": contract.sha256,
        "certificate": certificate.to_dict(),
        "wave5c_capability_rule": rule,
        "accounting": {
            "nominal_requests": NOMINAL_REQUESTS,
            "actual_attempts": attempts,
            "maximum_attempts": MAX_ATTEMPTS,
            "input_tokens": sum(
                response.usage.input_tokens
                for record in cache._records.values()
                for response in record.responses
            ),
            "output_tokens": sum(
                response.usage.output_tokens
                for record in cache._records.values()
                for response in record.responses
            ),
            "cost_microusd": actual_cost,
            "hard_cost_cap_microusd": ROUTE_COST_CAP_MICROUSD,
            "maximum_prereserved_cost_microusd": (
                MAX_ATTEMPTS * RESERVATION.max_cost_microusd
            ),
        },
        "boundaries": {
            "automatic_fallback": False,
            "factorial_outcomes_requested": False,
            "production_pins_set": False,
            "capability_pass_authorizes_full_study": False,
            "raw_provider_response_persisted": False,
            "api_key_persisted_or_hashed": False,
        },
    }


def certificate_request_attempts(cache: ExactReplayCache) -> int:
    return sum(len(record.responses) for record in cache._records.values())


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(value) + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capability", choices=("capability",))
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--api-key-file", required=True, type=Path)
    parser.add_argument("--audit-go", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        print("capability runner requires a fresh output directory", file=sys.stderr)
        return 2
    try:
        if sys.version_info[:3] != (3, 10, 13):
            raise CapabilityRunError("capability runner requires locked CPython 3.10.13")
        audit = json.loads(args.audit_go.read_text(encoding="utf-8"))
        if not isinstance(audit, Mapping):
            raise CapabilityRunError("independent adapter audit must be a JSON object")
        audit_binding = validate_independent_audit_go(
            audit, repository_root=args.repository_root
        )
        api_key = load_protected_api_key(
            args.api_key_file, repository_root=args.repository_root
        )
        contract = build_receiver_contract()
        transport = OpenAIResponsesTransport(contract, api_key)
        output_dir.mkdir(mode=0o700, parents=False)
        result = run_capability(transport)
        result["audit_binding"] = audit_binding
        _atomic_write(output_dir / "capability_certificate.json", result)
    except (
        CapabilityRunError,
        ControlledReceiverError,
        OpenAIAdapterError,
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Wave 5E capability failed closed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "certificate_path": str(output_dir / "capability_certificate.json"),
                "receiver_contract_sha256": result["receiver_contract_sha256"],
                "cost_microusd": result["accounting"]["cost_microusd"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUDIT_GO_SCHEMA",
    "MAX_ATTEMPTS",
    "NOMINAL_REQUESTS",
    "PINNED_SOURCE_PATHS",
    "ROUTE_COST_CAP_MICROUSD",
    "run_capability",
    "source_hashes",
    "validate_independent_audit_go",
]
