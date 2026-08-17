"""Audit-gated, supervisor-only Wave 5D bargaining Model-A v2 campaign."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from glee_eval.diagnostics.bargaining_model_a_evaluator_v2 import (
    final_verdict_v2,
    jordan_reached_diagnostics,
    score_oof_rows_v2,
    summarize_oof_v2,
)
from glee_eval.population.bargaining_model_a_v2 import (
    build_bargaining_manifest_v2,
    extract_corpus_v2,
    fit_outer_fold_v2,
    sha256_file,
    write_fold_artifact_v2,
)
from glee_eval.population.crossfit import manifest_sha256
from glee_eval.storage.trajectories import iter_jsonl, read_json, write_json_atomic


CONTRACT_SCHEMA = "glee.wave5d.bargaining_model_a_v2_prefit.v1"
AUDIT_SCHEMA = "glee.wave5d.bargaining_model_a_v2_prefit_audit.v1"
ROOT_GO_TOKEN = "WAVE5D_MODEL_A_V2_GO"
ARTIFACT_LIMIT_BYTES = 3 * 1024 ** 3
REQUIRED_AUDIT_CHECKS = (
    "contract_and_hash_identity",
    "feature_visibility_and_hostile_canaries",
    "explicit_censoring",
    "operational_v1_exact_execution",
    "inner_cv_game_weighting",
    "stable_content_row_identity",
    "external_resource_supervisor",
    "jordan_reached_diagnostics",
    "no_model_b_or_integration",
    "structural_outcomes_uninspected",
)


def _repository_root(contract_path: str | Path) -> Path:
    return Path(contract_path).resolve().parents[2]


def verify_contract_v2(contract_path: str | Path, *, verify_large_sources: bool = True) -> tuple[dict[str, Any], str]:
    path = Path(contract_path)
    payload = read_json(path)
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("unexpected Model-A v2 pre-fit contract schema")
    root = _repository_root(path)
    for name, source in payload.get("frozen_sources", {}).items():
        source_path = Path(source["path"])
        if not source_path.is_absolute():
            source_path = root / source_path
        if not source_path.exists():
            raise ValueError(f"frozen source absent: {name}")
        if verify_large_sources or name != "released_events":
            if sha256_file(source_path) != source["sha256"]:
                raise ValueError(f"frozen source mismatch: {name}")
    locked = payload.get("locked_code")
    if not isinstance(locked, dict) or not locked:
        raise ValueError("contract has no locked code map")
    for relative, expected in locked.items():
        implementation = root / relative
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise ValueError(f"invalid locked hash for {relative}")
        if not implementation.is_file() or sha256_file(implementation) != expected:
            raise ValueError(f"locked implementation mismatch: {relative}")
    if payload.get("resource_ceiling") != {
        "aggregate_rss_bytes": 7 * 1024 ** 3,
        "max_worker_threads": 6,
        "artifact_bytes": ARTIFACT_LIMIT_BYTES,
        "automatic_restarts": 0,
    }:
        raise ValueError("resource ceiling differs from Wave 5D authorization")
    return payload, sha256_file(path)


def verify_audit_v2(audit_path: str | Path, contract_sha256: str, contract: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(audit_path)
    if set(payload) != {
        "schema", "verdict", "contract_sha256", "audited_commit", "reviewed_code_sha256",
        "auditor_id", "auditor_fresh_context", "auditor_implemented_route_2", "reviewed_test_command",
        "reviewed_test_result", "checks", "objections", "notes", "structural_outcomes_inspected",
        "authorization",
    }:
        raise PermissionError("audit document has missing or unexpected top-level fields")
    if payload["schema"] != AUDIT_SCHEMA or payload["verdict"] != "pass":
        raise PermissionError("fresh independent pre-fit audit did not pass")
    if payload["contract_sha256"] != contract_sha256 or payload["reviewed_code_sha256"] != contract["locked_code"]:
        raise PermissionError("audit did not review this exact frozen formulation")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload["audited_commit"])):
        raise PermissionError("audit lacks an exact commit identity")
    if not str(payload["auditor_id"]).strip() or payload["auditor_fresh_context"] is not True:
        raise PermissionError("audit lacks fresh auditor identity")
    if payload["auditor_implemented_route_2"] is not False or payload["structural_outcomes_inspected"] is not False:
        raise PermissionError("audit independence/outcome-blinding attestation failed")
    if not str(payload["reviewed_test_command"]).strip() or not str(payload["reviewed_test_result"]).strip():
        raise PermissionError("audit lacks test evidence")
    checks = payload["checks"]
    if set(checks) != set(REQUIRED_AUDIT_CHECKS) or any(checks[name] != "pass" for name in REQUIRED_AUDIT_CHECKS):
        raise PermissionError("audit does not pass every exact mandatory check")
    if payload["objections"] != [] or payload["authorization"] != "prefit_go_eligible_root_token_still_required":
        raise PermissionError("audit contains objections or invalid authorization ceiling")
    return payload


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = list(iter_jsonl(path))
    row_ids = [str(row.get("row_id") or "") for row in rows]
    if len(set(row_ids)) != len(rows) or any(len(value) != 64 for value in row_ids):
        raise ValueError("extracted row identity reconciliation failed")
    return rows


def run_campaign_v2(args: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get("WAVE5D_EXTERNAL_SUPERVISOR_ACTIVE") != "1":
        raise PermissionError("campaign may run only as a child of the tested Wave 5D external supervisor")
    contract, contract_sha = verify_contract_v2(args.contract)
    audit = verify_audit_v2(args.audit, contract_sha, contract)
    if args.root_go != ROOT_GO_TOKEN:
        raise PermissionError("root orchestrator GO token absent")
    repository_root = _repository_root(args.contract)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repository_root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if commit != audit["audited_commit"] or dirty:
        raise PermissionError("execution checkout is not the exact clean independently audited commit")
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("campaign output directory must be new or empty; automatic restart is forbidden")
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source_path = contract["frozen_sources"]["released_events"]["path"]
    rows_path = output / "bargaining_rows_v2.jsonl"
    extraction = extract_corpus_v2(source_path, rows_path, artifact_byte_limit=ARTIFACT_LIMIT_BYTES)
    if extraction["source_sha256"] != contract["frozen_sources"]["released_events"]["sha256"]:
        raise ValueError("released source changed during extraction")
    write_json_atomic(output / "extraction.json", extraction)
    rows = _load_rows(rows_path)
    manifest = build_bargaining_manifest_v2(rows)
    manifest.update({"contract_sha256": contract_sha, "source_sha256": extraction["source_sha256"]})
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    manifest_path = output / "crossfit_manifest.json"
    write_json_atomic(manifest_path, manifest)

    artifacts: dict[str, list[dict[str, Any]]] = {"actor": [], "config": []}
    for axis, folds in (("actor", 3), ("config", 4)):
        for fold in range(folds):
            artifact = fit_outer_fold_v2(
                rows, axis=axis, fold=fold, manifest=manifest,
                source_sha256=extraction["source_sha256"], contract_sha256=contract_sha,
            )
            artifact_path = output / f"{axis}_fold_{fold}.json"
            write_fold_artifact_v2(artifact_path, artifact)
            artifacts[axis].append({
                "fold": fold, "path": str(artifact_path.resolve()),
                "sha256": sha256_file(artifact_path), "status": artifact["status"],
            })
            if _directory_bytes(output) > ARTIFACT_LIMIT_BYTES:
                raise RuntimeError("artifact byte ceiling exceeded")

    summaries, certificates_index, statuses = [], [], []
    for axis in ("actor", "config"):
        loaded: dict[int, dict[str, Any]] = {}
        for spec in artifacts[axis]:
            path = Path(spec["path"])
            if sha256_file(path) != spec["sha256"]:
                raise ValueError("fold artifact changed before OOF scoring")
            loaded[int(spec["fold"])] = read_json(path)
            statuses.append(spec["status"])
        certificates = score_oof_rows_v2(
            rows, axis=axis, manifest=manifest, artifacts=loaded,
            operational_population_path=contract["frozen_sources"]["operational_v1"]["path"],
            model_c_path=contract["frozen_sources"]["model_c"]["path"],
            v1_draws=int(contract["comparators"]["operational_v1"]["integration_draws"]),
        )
        certificate_path = output / f"{axis}_oof_certificates.jsonl"
        temporary = certificate_path.with_name(f".{certificate_path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for certificate in certificates:
                handle.write(json.dumps(certificate, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
        temporary.replace(certificate_path)
        certificates_index.append({
            "axis": axis, "path": str(certificate_path.resolve()),
            "sha256": sha256_file(certificate_path), "rows": len(certificates),
        })
        summaries.append(summarize_oof_v2(certificates, axis=axis))
    verdict = final_verdict_v2(summaries, statuses)
    jordan = jordan_reached_diagnostics(summaries)
    report = {
        "schema": "glee.wave5d.bargaining_model_a_v2_result.v1",
        "contract_path": str(Path(args.contract).resolve()),
        "contract_sha256": contract_sha,
        "prefit_audit_path": str(Path(args.audit).resolve()),
        "prefit_audit_sha256": sha256_file(args.audit),
        "prefit_auditor": audit["auditor_id"],
        "source_sha256": extraction["source_sha256"],
        "manifest_path": str(manifest_path.resolve()),
        "manifest_file_sha256": sha256_file(manifest_path),
        "manifest_declared_sha256": manifest["manifest_sha256"],
        "extraction": extraction,
        "fold_artifacts": artifacts,
        "oof_certificates": certificates_index,
        "axis_summaries": summaries,
        "verdict": verdict,
        "jordan_reached_diagnostics": jordan,
        "resource_usage": {
            "elapsed_monotonic_seconds": time.monotonic() - started,
            "artifact_bytes": _directory_bytes(output),
            "external_supervisor_certificate": "written by parent after child termination",
        },
        "postfit_audit": {"verdict": "pending_fresh_independent_auditor"},
        "integration_or_promotion_permitted": False,
    }
    report_path = output / "result.json"
    write_json_atomic(report_path, report)
    return {"report_path": str(report_path.resolve()), "report_sha256": sha256_file(report_path), "verdict": verdict}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--root-go", required=True)
    parser.add_argument("--output-dir", required=True)
    result = run_campaign_v2(parser.parse_args(argv))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
