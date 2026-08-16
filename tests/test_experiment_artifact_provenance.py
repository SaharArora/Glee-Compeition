from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from glee_eval.experiments.artifact_provenance import artifact_provenance
from glee_eval.simulate.dispatch import TargetedSimulationDispatcher


class ArtifactProvenanceTests(unittest.TestCase):
    def test_path_and_sha_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "opponent_population.json"
            path.write_bytes(b'{"schema_version":2}\n')
            found = artifact_provenance(path, path.name)
            self.assertEqual(found["path"], str(path.resolve()))
            self.assertEqual(found["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_dispatcher_copies_provenance_to_each_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = {"opponent_population": {"path": "/frozen/model.json", "sha256": "a" * 64}}
            dispatcher = TargetedSimulationDispatcher(
                agent_spec="heuristic", support_index={}, audit_report={}, seed=2,
                ledger_path=Path(tmp) / "ledger.jsonl", artifact_provenance=provenance,
            )
            result = dispatcher.policy_optimization_simulation(families=["negotiation"], games=1, output_dir=Path(tmp) / "out")
            self.assertEqual(result["episodes"][0].scenario.metadata["simulation"]["artifact_provenance"], provenance)


if __name__ == "__main__":
    unittest.main()
