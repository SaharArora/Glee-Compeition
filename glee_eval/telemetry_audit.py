"""Independent hostile verifier for a raw live-telemetry batch.

This module intentionally does not import or trust ``reconcile_batch``.  It
recomputes attribution from the immutable launch manifest and append-only event
ledger, so an implementation summary cannot certify itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

# Independent literal contract. Do not import these values from the subject
# implementation: a coherent subject+manifest mutation must still fail here.
AUDIT_EXPECTED_CANDIDATE_COMMIT = "bce578597dbfacf2ebca38399edb41a5dde2f936"
AUDIT_EXPECTED_AGENT_SPEC = "my_agents.jordan_strategic:MyAgent"
AUDIT_EXPECTED_AGENT_UUID = "99357c15-48d5-4177-9d6a-48d02b95a164"
AUDIT_EXPECTED_AGENT_NAME = "gangsteryoshi"
AUDIT_EXPECTED_POLICY_PATH = "my_agents/jordan_strategic.py"
AUDIT_EXPECTED_POLICY_SHA256 = "27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82"


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return events, ["event_ledger_missing"]
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append(f"malformed_event_line:{number}")
            continue
        if not isinstance(value, dict):
            errors.append(f"non_object_event_line:{number}")
            continue
        events.append(value)
    return events, errors


def audit_batch(
    output_dir: str | Path, *, expected_per_family: int | None = None,
    forbidden_secret_values: Sequence[str] = (),
) -> dict[str, Any]:
    out = Path(output_dir)
    errors: list[str] = []
    manifest_path = out / "launch_manifest.json"
    events_path = out / "telemetry.jsonl"
    raw_bytes = b""
    for path in (manifest_path, events_path):
        if path.exists():
            raw_bytes += path.read_bytes()
    for secret in forbidden_secret_values:
        if secret and secret.encode() in raw_bytes:
            errors.append("forbidden_secret_literal_present")
            break
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema": "glee.live.hostile_attribution_audit.v1",
            "verdict": "fail",
            "errors": [f"launch_manifest_unreadable:{type(exc).__name__}"] + errors,
            "attributable": False,
        }
    events, event_errors = _load_events(events_path)
    errors.extend(event_errors)
    config = manifest.get("configuration")
    if not isinstance(config, dict):
        errors.append("configuration_missing")
        config = {}
    recomputed_config_sha = _sha256(_canonical_bytes(config))
    if recomputed_config_sha != manifest.get("configuration_sha256"):
        errors.append("configuration_digest_mismatch")
    if config.get("candidate", {}).get("candidate_commit") != AUDIT_EXPECTED_CANDIDATE_COMMIT:
        errors.append("wrong_candidate_commit")
    if config.get("candidate", {}).get("entrypoint") != AUDIT_EXPECTED_AGENT_SPEC:
        errors.append("wrong_agent_entrypoint")
    if config.get("candidate", {}).get("policy_path") != AUDIT_EXPECTED_POLICY_PATH:
        errors.append("wrong_policy_path")
    if config.get("candidate", {}).get("policy_sha256") != AUDIT_EXPECTED_POLICY_SHA256:
        errors.append("wrong_policy_digest")
    if config.get("git", {}).get("dirty") is not False:
        errors.append("launch_tree_dirty")
    clean_git_digest = _sha256(_canonical_bytes({
        "tracked_diff_sha256": _sha256(b""),
        "untracked": [],
    }))
    if config.get("git", {}).get("dirty") is False and (
        config.get("git", {}).get("dirty_digest") != clean_git_digest
        or config.get("git", {}).get("tracked_diff_sha256") != _sha256(b"")
        or config.get("git", {}).get("untracked") != []
    ):
        errors.append("clean_git_claim_internally_inconsistent")
    expected_identity = config.get("agent_identity_expected", {})
    if expected_identity != {"uuid": AUDIT_EXPECTED_AGENT_UUID, "name": AUDIT_EXPECTED_AGENT_NAME}:
        errors.append("wrong_expected_identity")
    identity_events = [row for row in events if row.get("event_type") == "identity_verified"]
    if len(identity_events) != 1:
        errors.append("identity_verification_not_unique")
    elif identity_events[0].get("identity", {}).get("uuid") != AUDIT_EXPECTED_AGENT_UUID \
            or identity_events[0].get("identity", {}).get("name") != AUDIT_EXPECTED_AGENT_NAME:
        errors.append("observed_identity_mismatch")
    sequences = [row.get("sequence") for row in events]
    if sequences != list(range(1, len(events) + 1)):
        errors.append("event_sequence_not_contiguous")
    previous_hash: str | None = None
    for row in events:
        claimed = row.get("event_sha256")
        unhashed = dict(row)
        unhashed.pop("event_sha256", None)
        if row.get("previous_event_sha256") != previous_hash or claimed != _sha256(_canonical_bytes(unhashed)):
            errors.append("event_hash_chain_mismatch")
            break
        previous_hash = str(claimed)
    if any(row.get("batch_id") != manifest.get("batch_id") for row in events):
        errors.append("event_batch_link_mismatch")
    if any(row.get("configuration_sha256") != recomputed_config_sha for row in events):
        errors.append("event_configuration_link_mismatch")

    actions = {str(row.get("game_id")) for row in events if row.get("event_type") == "action_prepared"}
    terminals = [
        row for row in events
        if row.get("event_type") in ("move_result", "terminal_backfill") and row.get("terminal") is True
    ]
    terminal_ids = [str(row.get("game_id")) for row in terminals]
    duplicates = sorted(game_id for game_id, count in Counter(terminal_ids).items() if count != 1)
    if duplicates:
        errors.append("duplicate_terminal")
    if set(terminal_ids) - actions:
        errors.append("terminal_without_action")
    required = ("game_id", "scenario_id", "family", "role", "payoff", "terminal_status", "timestamp_utc")
    for row in terminals:
        if any(row.get(field) is None for field in required):
            errors.append("terminal_required_field_missing")
            break
    official_missing = [
        str(row.get("game_id")) for row in terminals
        if row.get("official_scoring", {}).get("game_rating", {}).get("status") != "available"
    ]
    family_counts = Counter(str(row.get("family")) for row in terminals)
    per_family = int(config.get("per_family_games") or 0)
    if expected_per_family is not None and per_family != expected_per_family:
        errors.append("unexpected_declared_batch_size")
    exact_counts = all(family_counts.get(family, 0) == per_family for family in config.get("families", []))
    if not exact_counts:
        errors.append("partial_batch")
    if official_missing:
        errors.append("official_per_game_rating_unavailable")
    fatal_types = {
        "batch_crash", "cap_violation", "duplicate_game_conflict", "duplicate_terminal",
        "move_api_failure", "move_timeout", "backfill_failure", "unresolved_terminal_stop",
        "preflight_failure",
    }
    if any(row.get("event_type") in fatal_types for row in events):
        errors.append("fatal_runtime_event")
    errors = sorted(set(errors))
    return {
        "schema": "glee.live.hostile_attribution_audit.v1",
        "verdict": "pass" if not errors else "fail",
        "attributable": not errors,
        "errors": errors,
        "configuration_sha256": recomputed_config_sha,
        "events": len(events),
        "terminal_games": len(set(terminal_ids)),
        "family_terminal_counts": dict(sorted(family_counts.items())),
        "official_game_rating_unavailable_game_ids": sorted(official_missing),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Hostile audit of raw GLEE canary telemetry")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-per-family", type=int, default=100)
    args = parser.parse_args(argv)
    report = audit_batch(args.output_dir, expected_per_family=args.expected_per_family)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["verdict"] == "pass" else 2)


if __name__ == "__main__":
    main()
