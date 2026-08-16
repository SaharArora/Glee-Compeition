"""Fit and freeze the eight artifacts required by exhaustive Model-B cross-fit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from glee_eval.population.crossfit import CrossfitRouter, build_manifest, fold_count
from glee_eval.population.opponent_fit import fit_opponent_population
from glee_eval.storage.trajectories import iter_jsonl


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def fit_crossfit_population(
    *,
    data_dir: str | Path,
    output_dir: str | Path,
    fitter: Callable[..., dict[str, Any]] = fit_opponent_population,
) -> dict[str, Any]:
    """Build the immutable manifest, fit every artifact per axis, and lock their SHAs."""

    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    events_path = data_dir / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")
    manifest = build_manifest(iter_jsonl(events_path))
    manifest_path = output_dir / "crossfit_manifest.json"
    _atomic_json(manifest_path, manifest)

    artifacts_by_axis: dict[str, list[dict[str, Any]]] = {}
    for axis in ("actor", "config"):
        specs: list[dict[str, Any]] = []
        folds = fold_count(axis)
        for fold in range(folds):
            print(f"phase=fit axis={axis} fold={fold}/{folds - 1}", file=sys.stderr, flush=True)
            fold_dir = output_dir / f"{axis}_fold_{fold}"
            fitter(
                data_dir,
                fold_dir,
                split_mode="none",
                split=None,
                holdout_fraction=0.25,
                crossfit_manifest=manifest,
                excluded_fold=fold,
                crossfit_axis=axis,
            )
            artifact_path = (fold_dir / "opponent_population.json").resolve()
            if not artifact_path.exists():
                raise FileNotFoundError(f"fitter did not produce {artifact_path}")
            specs.append({"path": str(artifact_path), "sha256": _sha256(artifact_path)})
        # Refuse to serialize a spec that the production validator would reject.
        CrossfitRouter(manifest, axis, specs)
        artifacts_by_axis[axis] = specs

    spec = {
        "schema_version": 1,
        "declaration": "docs/REGISTRY.md model_b_crossfit_joint_opponents",
        "data_events_path": str(events_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_file_sha256": _sha256(manifest_path),
        "declared_manifest_sha256": manifest["manifest_sha256"],
        "actor_artifacts": artifacts_by_axis["actor"],
        "config_artifacts": artifacts_by_axis["config"],
    }
    spec_path = output_dir / "crossfit_spec.json"
    _atomic_json(spec_path, spec)
    return {**spec, "spec_path": str(spec_path.resolve())}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fit provenance-locked per-axis Model-B artifacts.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    result = fit_crossfit_population(data_dir=args.data_dir, output_dir=args.output_dir)
    print(json.dumps({
        "spec_path": result["spec_path"],
        "manifest_sha256": result["declared_manifest_sha256"],
        "actor_artifacts": len(result["actor_artifacts"]),
        "config_artifacts": len(result["config_artifacts"]),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
