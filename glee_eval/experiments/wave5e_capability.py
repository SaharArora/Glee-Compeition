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
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import glee_eval.experiments.controlled_receiver as controlled_receiver_module
import glee_eval.experiments.openai_responses as openai_responses_module
import glee_eval.experiments.receiver_itt as receiver_itt_module
import glee_eval.experiments.wave5c_receiver as wave5c_receiver_module
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
ROUTE_RUNTIME_CAP_SECONDS = 6_000.0
MAX_AUDIT_DOCUMENT_BYTES = 1_048_576
RESERVATION = CallReservation(
    input_tokens=2048,
    max_output_tokens=16,
    max_cost_microusd=4_224,
)
PINNED_SOURCE_PATHS = (
    "glee_eval/experiments/controlled_receiver.py",
    "glee_eval/experiments/openai_responses.py",
    "glee_eval/experiments/receiver_itt.py",
    "glee_eval/experiments/factorial.py",
    "glee_eval/experiments/factorial_report.py",
    "glee_eval/experiments/preoutcome_manifest.py",
    "glee_eval/experiments/wave5c_receiver.py",
    "glee_eval/experiments/wave5e_capability.py",
    "research/LOCKS/WAVE5E_OPENAI_ADAPTER_LOCK.json",
)


class CapabilityRunError(RuntimeError):
    pass


def _sha256_regular_file(path: Path) -> str:
    if stat.S_ISLNK(path.lstat().st_mode):
        raise CapabilityRunError(f"pinned source must not be a symlink: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CapabilityRunError(f"pinned source is not regular: {path.name}")
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def source_hashes(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve(strict=True)
    output: dict[str, str] = {}
    for name in PINNED_SOURCE_PATHS:
        path = root / name
        if not path.exists() or path.resolve(strict=True) != path:
            raise CapabilityRunError(f"pinned adapter source is missing: {name}")
        output[name] = _sha256_regular_file(path)
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


def validate_dependency_lock(repository_root: str | Path) -> None:
    root = Path(repository_root).resolve(strict=True)
    lock_path = root / "research/LOCKS/WAVE5E_OPENAI_ADAPTER_LOCK.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityRunError("adapter dependency lock is unreadable") from exc
    exact = {
        "python": lock.get("python"),
        "external_python_packages": lock.get("external_python_packages"),
        "network": lock.get("network"),
        "receiver": lock.get("receiver"),
        "pricing_microusd_per_token": lock.get("pricing_microusd_per_token"),
        "capability_route": lock.get("capability_route"),
    }
    expected = {
        "python": {"implementation": "CPython", "requires": "==3.10.13"},
        "external_python_packages": [],
        "network": {
            "scheme": "https",
            "host": "api.openai.com",
            "path": "/v1/responses",
            "redirects": "disabled_fail_closed",
            "proxy_environment": "ignored_direct_connection_only",
            "maximum_response_body_bytes": openai_responses_module.MAX_RESPONSE_BODY_BYTES,
        },
        "receiver": {
            "provider": "openai",
            "model_alias": "gpt-4.1",
            "immutable_snapshot": openai_responses_module.FROZEN_MODEL,
            "structured_output": "strict_json_schema",
            "provider_seed_parameter_sent": False,
            "receiver_seed_scope": "request_identity_and_cache_partition_only",
            "automatic_fallback": False,
        },
        "pricing_microusd_per_token": {
            "input": openai_responses_module.INPUT_MICROUSD_PER_TOKEN,
            "output": openai_responses_module.OUTPUT_MICROUSD_PER_TOKEN,
        },
        "capability_route": {
            "nominal_requests": NOMINAL_REQUESTS,
            "maximum_attempts": MAX_ATTEMPTS,
            "wall_clock_cap_seconds": int(ROUTE_RUNTIME_CAP_SECONDS),
            "hard_cost_cap_microusd": ROUTE_COST_CAP_MICROUSD,
            "maximum_prereserved_cost_microusd": (
                MAX_ATTEMPTS * RESERVATION.max_cost_microusd
            ),
        },
    }
    if exact != expected:
        raise CapabilityRunError("adapter dependency lock differs from runtime constants")
    runtime = lock.get("runtime_binding")
    if not isinstance(runtime, Mapping) or runtime.get("audited_source_paths") != list(
        PINNED_SOURCE_PATHS
    ):
        raise CapabilityRunError("dependency lock source list differs from runtime pins")


def validate_runtime_and_sources(repository_root: str | Path) -> dict[str, str]:
    """Bind executing imports, clean worktree bytes, and HEAD blobs to one root."""

    root = Path(repository_root).resolve(strict=True)
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if Path(top).resolve(strict=True) != root:
        raise CapabilityRunError("repository root is not the exact Git toplevel")
    validate_dependency_lock(root)
    module_paths = {
        "glee_eval/experiments/controlled_receiver.py": controlled_receiver_module.__file__,
        "glee_eval/experiments/openai_responses.py": openai_responses_module.__file__,
        "glee_eval/experiments/receiver_itt.py": receiver_itt_module.__file__,
        "glee_eval/experiments/wave5c_receiver.py": wave5c_receiver_module.__file__,
        "glee_eval/experiments/wave5e_capability.py": __file__,
    }
    for name, loaded in module_paths.items():
        try:
            resolved_module = (
                None if loaded is None else Path(loaded).resolve(strict=True)
            )
        except OSError:
            resolved_module = None
        if resolved_module != (root / name):
            raise CapabilityRunError(f"executing module is outside audited root: {name}")
    hashes = source_hashes(root)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *PINNED_SOURCE_PATHS],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise CapabilityRunError("audited source set is dirty")
    for name, observed in hashes.items():
        blob = subprocess.run(
            ["git", "show", f"HEAD:{name}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        if hashlib.sha256(blob).hexdigest() != observed:
            raise CapabilityRunError(f"working source differs from HEAD blob: {name}")
    return hashes


def _outside_repository(path: Path, repository_root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        return resolved
    raise CapabilityRunError(f"{label} must be outside the repository")


def _read_audit_document(path: Path, repository_root: Path) -> Mapping[str, Any]:
    absolute = path.expanduser().absolute()
    if stat.S_ISLNK(absolute.lstat().st_mode):
        raise CapabilityRunError("audit document must not be a symbolic link")
    safe = _outside_repository(absolute, repository_root, "audit document")
    if safe != absolute:
        raise CapabilityRunError("audit document path must not traverse symbolic links")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(safe, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CapabilityRunError("audit document must be a regular file")
        raw = os.read(descriptor, MAX_AUDIT_DOCUMENT_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_AUDIT_DOCUMENT_BYTES:
        raise CapabilityRunError("audit document exceeds the frozen byte limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise CapabilityRunError("independent adapter audit must be a JSON object")
    return value


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
    auditor = audit.get("independent_auditor")
    if (
        audit.get("verdict") != "GO"
        or not isinstance(auditor, str)
        or not auditor.strip()
    ):
        raise CapabilityRunError("independent adapter audit did not issue GO")
    if audit.get("automatic_fallback") is not False:
        raise CapabilityRunError("independent adapter audit permits fallback")
    if audit.get("api_call_performed_by_audit") is not False:
        raise CapabilityRunError("adapter audit must be offline")
    head = _git_head(root)
    if audit.get("implementation_commit") != head:
        raise CapabilityRunError("independent adapter audit covers another Git commit")
    observed_hashes = audit.get("source_sha256")
    expected_hashes = validate_runtime_and_sources(root)
    if observed_hashes != expected_hashes:
        raise CapabilityRunError("independent adapter audit source hashes do not match")
    return {
        "implementation_commit": head,
        "independent_auditor": auditor.strip(),
        "source_sha256": expected_hashes,
    }


class PreauthorizedRouteTransport:
    """Debit the conservative reservation before every external attempt."""

    def __init__(self, transport: OpenAIResponsesTransport) -> None:
        self.transport = transport
        self.contract = transport.contract
        self.started_at = time.monotonic()
        self.attempts_started = 0
        self.reserved_cost_microusd = 0

    def __call__(self, outbound: bytes, timeout: float):
        if time.monotonic() - self.started_at >= ROUTE_RUNTIME_CAP_SECONDS:
            raise CapabilityRunError("capability route runtime cap is exhausted")
        proposed_attempts = self.attempts_started + 1
        proposed_cost = self.reserved_cost_microusd + RESERVATION.max_cost_microusd
        if proposed_attempts > MAX_ATTEMPTS or proposed_cost > ROUTE_COST_CAP_MICROUSD:
            raise CapabilityRunError("capability route preauthorization cap is exhausted")
        self.attempts_started = proposed_attempts
        self.reserved_cost_microusd = proposed_cost
        result = self.transport(outbound, timeout)
        if time.monotonic() - self.started_at > ROUTE_RUNTIME_CAP_SECONDS:
            raise CapabilityRunError("capability route exceeded its runtime cap")
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "attempts_started": self.attempts_started,
            "maximum_attempts": MAX_ATTEMPTS,
            "conservative_reserved_cost_microusd": self.reserved_cost_microusd,
            "hard_cost_cap_microusd": ROUTE_COST_CAP_MICROUSD,
            "unknown_usage_is_zero": False,
        }


def run_capability(
    transport: OpenAIResponsesTransport | PreauthorizedRouteTransport,
) -> dict[str, Any]:
    route = (
        transport
        if isinstance(transport, PreauthorizedRouteTransport)
        else PreauthorizedRouteTransport(transport)
    )
    contract = build_receiver_contract()
    if route.contract.sha256 != contract.sha256:
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
        transport=route,
        reservation=RESERVATION,
        cache=cache,
    )
    rule = capability_rule_summary(certificate)
    attempts = sum(len(item.responses) for item in cache._records.values())
    if (
        attempts != certificate_request_attempts(cache)
        or attempts != route.attempts_started
        or attempts > MAX_ATTEMPTS
    ):
        raise CapabilityRunError("capability attempts exceed or contradict the frozen ceiling")
    if cache._records.keys() and len(cache._records) != NOMINAL_REQUESTS:
        raise CapabilityRunError("capability did not retain exactly 100 nominal request records")
    if certificate.contract_sha256 != contract.sha256:
        raise CapabilityRunError("capability certificate is bound to another receiver contract")
    if certificate.evidence_label != "infrastructure_only_non_evidence":
        raise CapabilityRunError("capability certificate has an invalid evidence class")
    if route.contract.max_attempts * NOMINAL_REQUESTS != MAX_ATTEMPTS:
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
            "preauthorization": route.snapshot(),
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


def capability_failure_certificate(
    route: PreauthorizedRouteTransport,
    audit_binding: Mapping[str, Any],
    exc: BaseException,
) -> dict[str, Any]:
    return {
        "schema": RUN_SCHEMA,
        "status": "FAIL",
        "stop_reason": type(exc).__name__,
        "error_detail_persisted": False,
        "accounting": route.snapshot(),
        "audit_binding": dict(audit_binding),
        "boundaries": {
            "automatic_fallback": False,
            "factorial_outcomes_requested": False,
            "production_pins_set": False,
            "capability_pass_authorizes_full_study": False,
            "raw_provider_response_persisted": False,
            "api_key_persisted_or_hashed": False,
        },
    }


def _create_fresh_output_dir(path: Path, repository_root: Path) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.exists() or absolute.is_symlink():
        raise CapabilityRunError("capability runner requires a fresh output directory")
    parent = absolute.parent.resolve(strict=True)
    if parent != absolute.parent:
        raise CapabilityRunError("output path must not traverse symbolic links")
    target = parent / absolute.name
    try:
        target.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise CapabilityRunError("capability output directory must be outside the repository")
    os.mkdir(target, 0o700)
    descriptor = os.open(
        target,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        created = os.fstat(descriptor)
        if not stat.S_ISDIR(created.st_mode) or stat.S_IMODE(created.st_mode) != 0o700:
            raise CapabilityRunError("capability output directory mode is not exactly 0700")
    finally:
        os.close(descriptor)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capability", choices=("capability",))
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--api-key-file", required=True, type=Path)
    parser.add_argument("--audit-go", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    output_dir: Path | None = None
    route: PreauthorizedRouteTransport | None = None
    audit_binding: dict[str, Any] | None = None
    try:
        if sys.version_info[:3] != (3, 10, 13):
            raise CapabilityRunError("capability runner requires locked CPython 3.10.13")
        repository_root = args.repository_root.resolve(strict=True)
        audit = _read_audit_document(args.audit_go, repository_root)
        audit_binding = validate_independent_audit_go(
            audit, repository_root=repository_root
        )
        api_key = load_protected_api_key(
            args.api_key_file, repository_root=repository_root
        )
        contract = build_receiver_contract()
        transport = OpenAIResponsesTransport(contract, api_key)
        output_dir = _create_fresh_output_dir(args.output_dir, repository_root)
        route = PreauthorizedRouteTransport(transport)
        result = run_capability(route)
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
        if output_dir is not None and route is not None and audit_binding is not None:
            failure = capability_failure_certificate(route, audit_binding, exc)
            _atomic_write(output_dir / "capability_certificate.json", failure)
            print(
                json.dumps(
                    {
                        "status": "FAIL",
                        "certificate_path": str(
                            output_dir / "capability_certificate.json"
                        ),
                        "stop_reason": type(exc).__name__,
                    },
                    sort_keys=True,
                )
            )
            return 1
        print(f"Wave 5E capability preflight failed closed: {type(exc).__name__}", file=sys.stderr)
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
    "PreauthorizedRouteTransport",
    "ROUTE_COST_CAP_MICROUSD",
    "ROUTE_RUNTIME_CAP_SECONDS",
    "capability_failure_certificate",
    "run_capability",
    "source_hashes",
    "validate_independent_audit_go",
    "validate_dependency_lock",
    "validate_runtime_and_sources",
]
