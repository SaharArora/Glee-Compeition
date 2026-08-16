"""Immutable per-axis cross-fit manifests and leak-proof artifact routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from glee_eval.population.config_keys import canonical_config_key

AXIS_FOLDS = {"actor": 3, "config": 4}
AXIS_HOLDOUT_FRACTIONS = {"actor": 1.0 / 3.0, "config": 0.25}


def fold_count(axis: str) -> int:
    if axis not in AXIS_FOLDS:
        raise ValueError("axis must be actor or config")
    return AXIS_FOLDS[axis]


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def acting_model(row: dict[str, Any]) -> str:
    role = str(row.get("role") or "")
    field = "player_1_model" if role in {"player_1", "seller"} else "player_2_model"
    model = str(row.get(field) or "")
    if not model:
        raise ValueError(f"missing acting-role model for role {role!r}")
    return model


def canonical_key(row: dict[str, Any]) -> str:
    config = row.get("configuration") or row.get("public_parameters") or {}
    if isinstance(config, str):
        config = json.loads(config)
    if isinstance(config, dict):
        config = config.get("game_args") or config
    return canonical_config_key(str(row.get("game_family") or ""), dict(config))


def config_fold(key: str) -> int:
    return int(_sha(key)[:16], 16) % AXIS_FOLDS["config"]


def build_manifest(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    identities_seen: set[str] = set()
    configs_seen: set[str] = set()
    for row in rows:
        identities_seen.add(acting_model(row))
        configs_seen.add(canonical_key(row))
    identities = sorted(identities_seen, key=lambda value: (_sha(value), value))
    if len(identities) != 15:
        raise ValueError(f"actor cross-fit requires exactly 15 identities, found {len(identities)}")
    actor_folds = {identity: index % AXIS_FOLDS["actor"] for index, identity in enumerate(identities)}
    configs = sorted(configs_seen)
    config_folds = {key: config_fold(key) for key in configs}
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "axis_folds": dict(AXIS_FOLDS),
        "axis_holdout_fractions": dict(AXIS_HOLDOUT_FRACTIONS),
        "actor_identity_hashes": {_sha(identity): actor_folds[identity] for identity in identities},
        "config_signature_hashes": {_sha(key): config_folds[key] for key in configs},
    }
    manifest["folds_manifest"] = {
        axis: {
            str(fold): {
                "evaluation_key_hashes": sorted(key_hash for key_hash, assigned in assignments.items() if assigned == fold),
                "training_key_hashes": sorted(key_hash for key_hash, assigned in assignments.items() if assigned != fold),
            }
            for fold in range(AXIS_FOLDS[axis])
        }
        for axis, assignments in (
            ("actor", manifest["actor_identity_hashes"]),
            ("config", manifest["config_signature_hashes"]),
        )
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def manifest_sha256(manifest: dict[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return _sha(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def row_fold(row: dict[str, Any], axis: str, manifest: dict[str, Any]) -> int:
    if axis == "actor":
        key_hash = _sha(acting_model(row))
        assignments = manifest["actor_identity_hashes"]
    elif axis == "config":
        key_hash = _sha(canonical_key(row))
        assignments = manifest["config_signature_hashes"]
    else:
        raise ValueError("axis must be actor or config")
    if key_hash not in assignments:
        raise ValueError(f"row key is absent from immutable {axis} manifest")
    return int(assignments[key_hash])


def filter_rows(rows: Iterable[dict[str, Any]], *, axis: str, fold: int, manifest: dict[str, Any], evaluation: bool) -> list[dict[str, Any]]:
    if fold not in range(fold_count(axis)):
        raise ValueError(f"fold must be 0..{fold_count(axis) - 1} for {axis}")
    return [row for row in rows if (row_fold(row, axis, manifest) == fold) is evaluation]


@dataclass(frozen=True)
class RoutedArtifact:
    axis: str
    fold: int
    path: Path
    sha256: str
    payload: dict[str, Any]


class CrossfitRouter:
    """Load every provenance-locked artifact for one axis and route OOF rows."""

    def __init__(self, manifest: dict[str, Any], axis: str, artifacts: Iterable[dict[str, Any]]):
        if manifest.get("manifest_sha256") != manifest_sha256(manifest):
            raise ValueError("cross-fit manifest SHA mismatch")
        if axis not in {"actor", "config"}:
            raise ValueError("axis must be actor or config")
        expected_folds = fold_count(axis)
        expected_fraction = AXIS_HOLDOUT_FRACTIONS[axis]
        if (
            (manifest.get("axis_folds") or {}).get(axis) != expected_folds
            or (manifest.get("axis_holdout_fractions") or {}).get(axis) != expected_fraction
        ):
            raise ValueError("cross-fit manifest axis fold/fraction contract mismatch")
        routed: dict[int, RoutedArtifact] = {}
        seen_paths: set[Path] = set()
        for spec in artifacts:
            path = Path(spec["path"]).resolve()
            if path in seen_paths:
                raise ValueError("duplicate cross-fit artifact path")
            seen_paths.add(path)
            raw = path.read_bytes()
            digest = _sha(raw)
            if digest != spec.get("sha256"):
                raise ValueError(f"artifact SHA mismatch: {path}")
            payload = json.loads(raw)
            provenance = payload.get("crossfit_provenance") or {}
            fold = int(provenance.get("fold", -1))
            if fold in routed:
                raise ValueError(f"duplicate cross-fit fold {fold}")
            expected = manifest["folds_manifest"][axis][str(fold)] if fold in range(expected_folds) else None
            if (
                expected is None or provenance.get("axis") != axis
                or provenance.get("folds") != expected_folds
                or provenance.get("holdout_fraction") != expected_fraction
                or provenance.get("manifest_sha256") != manifest["manifest_sha256"]
                or sorted(provenance.get("training_key_hashes") or []) != expected["training_key_hashes"]
                or sorted(provenance.get("evaluation_key_hashes") or []) != expected["evaluation_key_hashes"]
            ):
                raise ValueError(f"artifact fold provenance mismatch: {path}")
            if set(provenance["training_key_hashes"]) & set(provenance["evaluation_key_hashes"]):
                raise ValueError(f"heldout key leaked into training artifact: {path}")
            training = set(provenance["training_key_hashes"])
            evaluation = set(provenance["evaluation_key_hashes"])
            for bundles in (payload.get("joint_bundles") or {}).values():
                for bundle in bundles or []:
                    raw_key = bundle.get("player_model") if axis == "actor" else bundle.get("config_signature")
                    if raw_key is None:
                        raise ValueError(f"artifact bundle lacks {axis} routing identity: {path}")
                    key_hash = _sha(str(raw_key))
                    if key_hash in evaluation or key_hash not in training:
                        raise ValueError(f"heldout identity/signature leaked into artifact: {path}")
            coefficient_prefix = "model|" if axis == "actor" else "config|"
            for fit in ((payload.get("joint_model") or {}).get("response_estimators") or {}).values():
                for coefficient in (fit.get("coefficients") or {}):
                    if not str(coefficient).startswith(coefficient_prefix):
                        continue
                    raw_key = str(coefficient).rsplit("|", 1)[-1]
                    key_hash = _sha(raw_key)
                    if key_hash in evaluation or key_hash not in training:
                        raise ValueError(f"heldout response coefficient leaked into artifact: {path}")
            routed[fold] = RoutedArtifact(axis, fold, path, digest, payload)
        if set(routed) != set(range(expected_folds)):
            raise ValueError(f"router requires exactly one artifact for each of {expected_folds} {axis} folds")
        self.manifest = manifest
        self.axis = axis
        self.artifacts = routed

    def route(self, row: dict[str, Any]) -> RoutedArtifact:
        return self.artifacts[row_fold(row, self.axis, self.manifest)]
