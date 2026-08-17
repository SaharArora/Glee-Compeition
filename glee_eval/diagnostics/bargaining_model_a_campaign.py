"""Bounded, provenance-locked runner for the frozen bargaining Model-A campaign.

The public ``run`` command is intentionally unavailable before the pre-fit
contract's audit state is changed to ``passed`` by a fresh auditor.  Each outer
fold is fitted in its own subprocess and atomically certified.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from glee_eval.diagnostics.bargaining_model_a_evaluator import final_verdict, score_oof_rows, summarize_oof
from glee_eval.population.bargaining_model_a import (
    build_bargaining_manifest,
    extract_corpus,
    fit_outer_fold,
    sha256_file,
    write_fold_artifact,
)
from glee_eval.storage.trajectories import iter_jsonl, read_json, write_json_atomic
from glee_eval.population.crossfit import manifest_sha256
from glee_eval.storage.trajectories import canonical_json_sha256


CPU_HOURS_LIMIT = 8.0
WALL_HOURS_LIMIT = 8.0
FOLD_WALL_MINUTES_LIMIT = 90.0
RSS_GIB_LIMIT = 12.0
ARTIFACT_GIB_LIMIT = 3.0


def _rss_gib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    if sys.platform == "darwin":
        return value / 1024 ** 3
    return value * 1024 / 1024 ** 3


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def _verify_contract(contract_path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(contract_path)
    payload = read_json(path)
    if payload.get("schema") != "glee.wave5c.bargaining_model_a_prefit.v1":
        raise ValueError("unexpected Model-A pre-fit contract schema")
    repository_root = path.resolve().parents[2]
    for source in payload["frozen_sources"].values():
        source_path = Path(source["path"])
        if not source_path.is_absolute():
            source_path = repository_root / source_path
        if not source_path.exists() or sha256_file(source_path) != source["sha256"]:
            raise ValueError(f"frozen source mismatch: {source_path}")
    for relative, expected in payload["locked_code"].items():
        implementation = repository_root / relative
        if expected == "PENDING_PREFIT_FREEZE" or not implementation.exists() or sha256_file(implementation) != expected:
            raise ValueError(f"locked implementation mismatch: {implementation}")
    return payload, sha256_file(path)


def _verify_audit(audit_path: str | Path, contract_sha256: str, contract: dict[str, Any]) -> dict[str, Any]:
    path = Path(audit_path)
    payload = read_json(path)
    if payload.get("schema") != "glee.wave5c.bargaining_model_a_prefit_audit.v1":
        raise ValueError("unexpected pre-fit audit schema")
    if payload.get("verdict") != "pass":
        raise PermissionError("fresh independent pre-fit audit did not pass")
    if payload.get("contract_sha256") != contract_sha256:
        raise PermissionError("pre-fit audit did not review this exact contract")
    if payload.get("reviewed_code_sha256") != contract.get("locked_code"):
        raise PermissionError("pre-fit audit code hashes differ from the frozen package")
    if not payload.get("auditor_fresh_context") or payload.get("auditor_implemented_route_a") is not False:
        raise PermissionError("pre-fit audit lacks fresh non-implementer attestation")
    return payload


def fit_fold_command(args: argparse.Namespace) -> dict[str, Any]:
    started_wall = time.monotonic()
    started_cpu = time.process_time()
    contract, contract_sha = _verify_contract(args.contract)
    _verify_audit(args.audit, contract_sha, contract)
    if args.root_go != "WAVE5C_ROUTE_A_GO":
        raise PermissionError("root orchestrator GO token absent")
    rows_path = Path(args.rows)
    manifest_path = Path(args.manifest)
    if sha256_file(rows_path) != args.rows_sha256:
        raise ValueError("extracted rows SHA mismatch")
    manifest = read_json(manifest_path)
    rows = _load_rows(rows_path)
    artifact = fit_outer_fold(
        rows,
        axis=args.axis,
        fold=args.fold,
        manifest=manifest,
        source_sha256=contract["frozen_sources"]["released_events"]["sha256"],
        contract_sha256=contract_sha,
    )
    elapsed_wall = time.monotonic() - started_wall
    elapsed_cpu = time.process_time() - started_cpu
    artifact["resource_usage"] = {
        "wall_seconds": elapsed_wall,
        "cpu_seconds": elapsed_cpu,
        "peak_rss_gib": _rss_gib(),
    }
    resource_failure = []
    if elapsed_wall > FOLD_WALL_MINUTES_LIMIT * 60:
        resource_failure.append("single_fold_wall_over_90_minutes")
    if elapsed_cpu > CPU_HOURS_LIMIT * 3600:
        resource_failure.append("single_process_cpu_over_campaign_ceiling")
    if artifact["resource_usage"]["peak_rss_gib"] > RSS_GIB_LIMIT:
        resource_failure.append("rss_over_12_gib")
    if resource_failure:
        artifact["status"] = "resource_limit_failure"
        artifact["resource_failures"] = resource_failure
    artifact["payload_sha256"] = canonical_json_sha256({key: value for key, value in artifact.items() if key != "payload_sha256"})
    write_fold_artifact(args.output, artifact)
    return {"output": str(Path(args.output).resolve()), "status": artifact["status"], **artifact["resource_usage"]}


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run_campaign(args: argparse.Namespace) -> dict[str, Any]:
    started_wall = time.monotonic()
    contract, contract_sha = _verify_contract(args.contract)
    audit = _verify_audit(args.audit, contract_sha, contract)
    if args.root_go != "WAVE5C_ROUTE_A_GO":
        raise PermissionError("root orchestrator GO token absent")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    events = contract["frozen_sources"]["released_events"]["path"]
    rows_path = output / "bargaining_rows.jsonl"
    extraction = extract_corpus(events, rows_path)
    if extraction["source_sha256"] != contract["frozen_sources"]["released_events"]["sha256"]:
        raise ValueError("released event source changed during extraction")
    write_json_atomic(output / "extraction.json", extraction)
    rows = _load_rows(rows_path)
    manifest = build_bargaining_manifest(rows)
    manifest["contract_sha256"] = contract_sha
    manifest["source_sha256"] = extraction["source_sha256"]
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    manifest_path = output / "crossfit_manifest.json"
    write_json_atomic(manifest_path, manifest)

    artifacts: dict[str, list[dict[str, Any]]] = {"actor": [], "config": []}
    cpu_seconds = 0.0
    maximum_rss = _rss_gib()
    for axis, folds in (("actor", 3), ("config", 4)):
        for fold in range(folds):
            if time.monotonic() - started_wall > WALL_HOURS_LIMIT * 3600:
                raise RuntimeError("campaign wall-clock ceiling exceeded before next fold")
            artifact_path = output / f"{axis}_fold_{fold}.json"
            command = [
                sys.executable,
                "-m",
                "glee_eval.diagnostics.bargaining_model_a_campaign",
                "fit-fold",
                "--contract", str(Path(args.contract).resolve()),
                "--audit", str(Path(args.audit).resolve()),
                "--root-go", args.root_go,
                "--rows", str(rows_path.resolve()),
                "--rows-sha256", extraction["rows_sha256"],
                "--manifest", str(manifest_path.resolve()),
                "--axis", axis,
                "--fold", str(fold),
                "--output", str(artifact_path.resolve()),
            ]
            subprocess.run(command, check=True, timeout=FOLD_WALL_MINUTES_LIMIT * 60)
            artifact = read_json(artifact_path)
            cpu_seconds += float(artifact["resource_usage"]["cpu_seconds"])
            maximum_rss = max(maximum_rss, float(artifact["resource_usage"]["peak_rss_gib"]))
            artifacts[axis].append({
                "fold": fold,
                "path": str(artifact_path.resolve()),
                "sha256": sha256_file(artifact_path),
                "status": artifact["status"],
            })
            if cpu_seconds > CPU_HOURS_LIMIT * 3600:
                raise RuntimeError("campaign cumulative CPU ceiling exceeded")
            if maximum_rss > RSS_GIB_LIMIT:
                raise RuntimeError("campaign RSS ceiling exceeded")
            if _directory_bytes(output) > ARTIFACT_GIB_LIMIT * 1024 ** 3:
                raise RuntimeError("campaign artifact ceiling exceeded")

    axis_summaries = []
    certificate_specs = []
    artifact_statuses = []
    for axis in ("actor", "config"):
        loaded = {}
        for spec in artifacts[axis]:
            path = Path(spec["path"])
            if sha256_file(path) != spec["sha256"]:
                raise ValueError(f"fold artifact changed before scoring: {path}")
            loaded[int(spec["fold"])] = read_json(path)
            artifact_statuses.append(spec["status"])
        certificates = score_oof_rows(
            rows,
            axis=axis,
            manifest=manifest,
            artifacts=loaded,
            operational_population_path=contract["frozen_sources"]["operational_v1"]["path"],
            model_c_path=contract["frozen_sources"]["model_c"]["path"],
            v1_draws=int(contract["comparators"]["operational_v1"]["integration_draws"]),
        )
        certificate_path = output / f"{axis}_oof_certificates.jsonl"
        temporary = certificate_path.with_name(f".{certificate_path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for certificate in certificates:
                handle.write(json.dumps(certificate, sort_keys=True, separators=(",", ":")) + "\n")
        temporary.replace(certificate_path)
        certificate_specs.append({
            "axis": axis,
            "path": str(certificate_path.resolve()),
            "sha256": sha256_file(certificate_path),
            "rows": len(certificates),
        })
        axis_summaries.append(summarize_oof(certificates, axis=axis))

    verdict = final_verdict(axis_summaries, artifact_statuses)
    elapsed_wall = time.monotonic() - started_wall
    report = {
        "schema": "glee.wave5c.bargaining_model_a_result.v1",
        "contract_path": str(Path(args.contract).resolve()),
        "contract_sha256": contract_sha,
        "prefit_audit_path": str(Path(args.audit).resolve()),
        "prefit_audit_sha256": sha256_file(args.audit),
        "prefit_auditor": audit.get("auditor_id"),
        "source_sha256": extraction["source_sha256"],
        "manifest_path": str(manifest_path.resolve()),
        "manifest_file_sha256": sha256_file(manifest_path),
        "manifest_declared_sha256": manifest["manifest_sha256"],
        "extraction": extraction,
        "fold_artifacts": artifacts,
        "oof_certificates": certificate_specs,
        "axis_summaries": axis_summaries,
        "verdict": verdict,
        "policy_relevance": {
            "immutable_jordan_reached_live_branch_labels": [
                "bargaining/player_1/offer/coverage_low",
                "bargaining/player_2/offer/coverage_low",
                "bargaining/player_2/offer/mae_high",
            ],
            "selection_role": "diagnostic_only_never_training_selection",
            "exact_live_candidate_rescoring": "pending_postfit_adapter_check; no released score is relabeled as live evidence",
        },
        "resource_usage": {
            "wall_seconds": elapsed_wall,
            "fold_cpu_seconds_sum": cpu_seconds,
            "peak_rss_gib_max": maximum_rss,
            "artifact_bytes": _directory_bytes(output),
            "ceilings": {
                "wall_hours": WALL_HOURS_LIMIT,
                "cpu_hours": CPU_HOURS_LIMIT,
                "rss_gib": RSS_GIB_LIMIT,
                "artifact_gib": ARTIFACT_GIB_LIMIT,
                "single_fold_wall_minutes": FOLD_WALL_MINUTES_LIMIT,
            },
        },
        "postfit_audit": {"verdict": "pending_fresh_independent_auditor"},
    }
    if elapsed_wall > WALL_HOURS_LIMIT * 3600 or cpu_seconds > CPU_HOURS_LIMIT * 3600 or maximum_rss > RSS_GIB_LIMIT or report["resource_usage"]["artifact_bytes"] > ARTIFACT_GIB_LIMIT * 1024 ** 3:
        report["verdict"] = {
            **verdict,
            "status": "development_fail_resource_ceiling",
            "passes_all_frozen_endpoints": False,
            "failures": sorted(set(verdict["failures"] + ["resource_ceiling_exceeded"])),
        }
    report_path = output / "result.json"
    write_json_atomic(report_path, report)
    return {"report_path": str(report_path.resolve()), "report_sha256": sha256_file(report_path), "verdict": report["verdict"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fit = subparsers.add_parser("fit-fold")
    fit.add_argument("--contract", required=True)
    fit.add_argument("--audit", required=True)
    fit.add_argument("--root-go", required=True)
    fit.add_argument("--rows", required=True)
    fit.add_argument("--rows-sha256", required=True)
    fit.add_argument("--manifest", required=True)
    fit.add_argument("--axis", choices=["actor", "config"], required=True)
    fit.add_argument("--fold", type=int, required=True)
    fit.add_argument("--output", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--contract", required=True)
    run.add_argument("--audit", required=True)
    run.add_argument("--root-go", required=True)
    run.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    result = fit_fold_command(args) if args.command == "fit-fold" else run_campaign(args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
