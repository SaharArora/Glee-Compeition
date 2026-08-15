from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from glee_eval.data.stats import stats_from_live_observations
from glee_eval.storage.trajectories import write_jsonl


class ObservationStatsCliTests(unittest.TestCase):
    def test_live_observations_are_summarized_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            write_jsonl(path, [
                {"status": "ok", "game_family": "bargaining", "phase": "offer", "action_type": "offer"},
                {"status": "fallback_after_exception", "game_family": "negotiation", "phase": "decision",
                 "action_type": "decision", "schema_violations": [{"field": "history"}]},
            ])

            result = stats_from_live_observations(path)

            self.assertEqual(result["turns"], 2)
            self.assertEqual(result["fallbacks"], 1)
            self.assertEqual(result["fallback_rate"], 0.5)
            self.assertEqual(result["schema_violation_turns"], 1)
            self.assertEqual(result["schema_violations"], 1)

    def test_command_help_reaches_real_subcommand_parsers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for command, expected in (("stats", "--observations"), ("shadow-score", "--episodes")):
            completed = subprocess.run(
                [sys.executable, "-m", "glee_eval", command, "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(expected, completed.stdout)

    def test_missing_observation_log_is_not_reported_as_an_empty_run(self) -> None:
        with self.assertRaises(FileNotFoundError):
            stats_from_live_observations("/definitely/missing/observations.jsonl")

    def test_stats_cli_accepts_observation_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            write_jsonl(path, [{"status": "ok", "game_family": "persuasion", "phase": "buyer_decision"}])
            root = Path(__file__).resolve().parents[1]

            completed = subprocess.run(
                [sys.executable, "-m", "glee_eval", "stats", "--observations", str(path)],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertEqual(json.loads(completed.stdout)["turns"], 1)


if __name__ == "__main__":
    unittest.main()
