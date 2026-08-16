from __future__ import annotations

import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path

from glee_eval.population.crossfit import CrossfitRouter, acting_model, build_manifest, filter_rows, manifest_sha256


def _rows() -> list[dict]:
    rows = []
    for index in range(16):
        rows.append({
            "game_family": "persuasion", "game_id": f"g{index}",
            "role": "seller" if index % 2 == 0 else "buyer",
            "player_1_model": f"m{index}" if index % 2 == 0 else "opponent",
            "player_2_model": f"m{index}" if index % 2 else "opponent",
            "configuration": {"p": 0.4 + index / 100, "c": 0.2, "seller_message_type": "text"},
        })
    return rows


def _artifact(path: Path, manifest: dict, axis: str, fold: int) -> dict:
    expected = manifest["folds_manifest"][axis][str(fold)]
    payload = {"crossfit_provenance": {
        "axis": axis, "fold": fold, "folds": 4, "holdout_fraction": 0.25,
        "manifest_sha256": manifest["manifest_sha256"], **expected,
    }, "joint_bundles": {}}
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class CrossfitManifestTests(unittest.TestCase):
    def test_manifest_accepts_a_single_pass_event_stream(self) -> None:
        rows = _rows()
        consumed = 0

        def stream():
            nonlocal consumed
            for row in rows:
                consumed += 1
                yield row

        manifest = build_manifest(stream())
        self.assertEqual(consumed, len(rows))
        self.assertEqual(len(manifest["actor_identity_hashes"]), 16)

    def test_actor_assignment_is_permutation_invariant_and_balanced(self) -> None:
        rows = _rows()
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        first, second = build_manifest(rows), build_manifest(shuffled)
        self.assertEqual(first, second)
        self.assertEqual([list(first["actor_identity_hashes"].values()).count(fold) for fold in range(4)], [4] * 4)
        self.assertEqual(first["manifest_sha256"], manifest_sha256(first))

    def test_acting_role_not_other_player_selects_actor(self) -> None:
        seller, buyer = _rows()[0], _rows()[1]
        self.assertEqual(acting_model(seller), "m0")
        self.assertEqual(acting_model(buyer), "m1")

    def test_each_row_is_once_evaluation_and_three_times_training(self) -> None:
        rows, manifest = _rows(), build_manifest(_rows())
        for axis in ("actor", "config"):
            for row in rows:
                eval_count = sum(row in filter_rows(rows, axis=axis, fold=fold, manifest=manifest, evaluation=True) for fold in range(4))
                train_count = sum(row in filter_rows(rows, axis=axis, fold=fold, manifest=manifest, evaluation=False) for fold in range(4))
                self.assertEqual((eval_count, train_count), (1, 3))

    def test_canonical_defaults_ignore_omitted_equivalents(self) -> None:
        rows = _rows()
        manifest = build_manifest(rows)
        original = rows[0]
        explicit = {**original, "configuration": {**original["configuration"], "is_seller_know_cv": True,
                    "is_buyer_know_p": True, "allow_buyer_message": False, "is_myopic": False,
                    "total_rounds": 20, "v": 0}}
        from glee_eval.population.crossfit import canonical_key, config_fold
        self.assertEqual(canonical_key(original), canonical_key(explicit))
        self.assertEqual(config_fold(canonical_key(original)), config_fold(canonical_key(explicit)))


class CrossfitRouterTests(unittest.TestCase):
    def test_router_accepts_locked_four_artifacts_and_routes(self) -> None:
        manifest = build_manifest(_rows())
        with tempfile.TemporaryDirectory() as tmp:
            specs = [_artifact(Path(tmp) / f"f{fold}.json", manifest, "actor", fold) for fold in range(4)]
            router = CrossfitRouter(manifest, "actor", specs)
            routed = router.route(_rows()[0])
            self.assertIn(routed.fold, range(4))

    def test_router_rejects_wrong_sha_duplicate_and_leakage(self) -> None:
        manifest = build_manifest(_rows())
        with tempfile.TemporaryDirectory() as tmp:
            specs = [_artifact(Path(tmp) / f"f{fold}.json", manifest, "actor", fold) for fold in range(4)]
            wrong = [dict(spec) for spec in specs]
            wrong[0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                CrossfitRouter(manifest, "actor", wrong)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                CrossfitRouter(manifest, "actor", [specs[0], specs[0], specs[2], specs[3]])
            payload = json.loads(Path(specs[0]["path"]).read_text())
            leaked = payload["crossfit_provenance"]["evaluation_key_hashes"][0]
            payload["crossfit_provenance"]["training_key_hashes"].append(leaked)
            Path(specs[0]["path"]).write_text(json.dumps(payload), encoding="utf-8")
            specs[0]["sha256"] = hashlib.sha256(Path(specs[0]["path"]).read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "provenance mismatch|leaked"):
                CrossfitRouter(manifest, "actor", specs)

    def test_router_inspects_bundle_identity_for_heldout_leakage(self) -> None:
        rows = _rows()
        manifest = build_manifest(rows)
        with tempfile.TemporaryDirectory() as tmp:
            specs = [_artifact(Path(tmp) / f"f{fold}.json", manifest, "actor", fold) for fold in range(4)]
            from glee_eval.population.crossfit import row_fold
            fold = row_fold(rows[0], "actor", manifest)
            path = Path(specs[fold]["path"])
            payload = json.loads(path.read_text())
            payload["joint_bundles"] = {"persuasion": [{"player_model": acting_model(rows[0])}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            specs[fold]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "leaked"):
                CrossfitRouter(manifest, "actor", specs)


if __name__ == "__main__":
    unittest.main()
