from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from glee_eval.simulate.dispatch import TargetedSimulationDispatcher


class SimulationDispatcherTests(unittest.TestCase):
    def test_policy_optimization_tags_episode_trigger_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatcher = TargetedSimulationDispatcher(
                agent_spec="heuristic",
                support_index={"buckets": {}},
                audit_report={},
                seed=3,
                ledger_path=root / "simulation_ledger.jsonl",
            )

            result = dispatcher.policy_optimization_simulation(families=["negotiation"], games=2, output_dir=root / "tournament")

            self.assertEqual(len(result["episodes"]), 2)
            self.assertEqual(result["episodes"][0].scenario.metadata["simulation"]["trigger"], "policy_optimization")
            self.assertTrue((root / "simulation_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
