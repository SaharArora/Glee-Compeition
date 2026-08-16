from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.population.crossfit import AXIS_HOLDOUT_FRACTIONS, canonical_key, fold_count, row_fold
from glee_eval.population.crossfit_fit import fit_crossfit_population
from glee_eval.storage.trajectories import write_json


def _events() -> list[dict]:
    return [{
        "event_id": f"e{index}", "game_id": f"g{index}", "game_family": "bargaining",
        "role": "player_1", "player_1_model": f"m{index:02d}", "player_2_model": "other",
        "configuration": {"money_to_divide": 100, "delta_1": .9, "delta_2": .9,
                          "max_rounds": 12, "complete_information": True,
                          "messages_allowed": False},
    } for index in range(15)]


class CrossfitFitTests(unittest.TestCase):
    def test_fits_eight_artifacts_and_writes_router_valid_spec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events_path = root / "data" / "processed" / "events.jsonl"
            events_path.parent.mkdir(parents=True)
            events_path.write_text("".join(json.dumps(row) + "\n" for row in _events()))
            calls = []

            def fake_fitter(data_dir, output_dir, **kwargs):
                calls.append(kwargs)
                axis, fold, manifest = kwargs["crossfit_axis"], kwargs["excluded_fold"], kwargs["crossfit_manifest"]
                expected = manifest["folds_manifest"][axis][str(fold)]
                bundles = []
                for row in _events():
                    if row_fold(row, axis, manifest) != fold:
                        bundles.append({
                            "role": "player_1", "player_model": row["player_1_model"],
                            "config_signature": canonical_key(row),
                        })
                payload = {
                    "crossfit_provenance": {
                        "axis": axis, "fold": fold, "folds": fold_count(axis),
                        "holdout_fraction": AXIS_HOLDOUT_FRACTIONS[axis],
                        "manifest_sha256": manifest["manifest_sha256"],
                        "training_key_hashes": expected["training_key_hashes"],
                        "evaluation_key_hashes": expected["evaluation_key_hashes"],
                    },
                    "joint_bundles": {"bargaining": bundles},
                }
                write_json(Path(output_dir) / "opponent_population.json", payload)
                return payload

            result = fit_crossfit_population(
                data_dir=root / "data", output_dir=root / "models", fitter=fake_fitter,
            )
            self.assertEqual(len(calls), 7)
            self.assertEqual({call["crossfit_axis"] for call in calls}, {"actor", "config"})
            self.assertEqual({call["excluded_fold"] for call in calls}, {0, 1, 2, 3})
            self.assertEqual(len(result["actor_artifacts"]), 3)
            self.assertEqual(len(result["config_artifacts"]), 4)
            self.assertTrue(Path(result["spec_path"]).exists())
            frozen = json.loads(Path(result["spec_path"]).read_text())
            self.assertEqual(frozen["declared_manifest_sha256"], result["declared_manifest_sha256"])
            self.assertTrue(all(Path(item["path"]).is_absolute() for item in frozen["actor_artifacts"]))


if __name__ == "__main__":
    unittest.main()
