from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.CANDIDATES.r2_population_bound_kill_check import (
    TREATMENT_LABEL,
    distribution_free_future_upper_bound,
    run_kill_check,
)


class R2PopulationBoundKillCheckTests(unittest.TestCase):
    def test_only_uniform_bound_without_population_assumptions_is_one(self) -> None:
        for prefix in ([], [0], [1], [0, 1, 1, 0], [1] * 100):
            self.assertEqual(distribution_free_future_upper_bound(prefix), 1.0)
        with self.assertRaises(ValueError):
            distribution_free_future_upper_bound([2])

    def test_verified_training_artifact_closes_population_extension(self) -> None:
        payload = {
            "version": 1,
            "min_support": 50,
            "families": {
                "persuasion": {
                    "buckets": {
                        "__global__": {"probability": 0.5},
                        "rec=yes": {
                            "probability": 0.7,
                            "trials": 100,
                            "support_quality": 1.0,
                        },
                        "sparse": {
                            "probability": 0.8,
                            "trials": 2,
                            "support_quality": 1.0,
                        },
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            raw = json.dumps(payload, sort_keys=True).encode("utf-8")
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            report = run_kill_check(path, digest)
            self.assertEqual(report["model_c"]["controller_eligible_reference_buckets"], 1)
            self.assertEqual(report["candidate_bound"]["sharp_distribution_free_upper_bound"], 1.0)
            self.assertEqual(report["verdict"], "KILL_NONTRIVIAL_POPULATION_BOUND_EXTENSION")
            self.assertEqual(report["treatment_label"], TREATMENT_LABEL)
            self.assertFalse(report["holdout_inspected"])
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                run_kill_check(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
