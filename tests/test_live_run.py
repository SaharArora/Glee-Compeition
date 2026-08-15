from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.live.run import capturing_client_class, play


class _FakeClient:
    responses: list[dict] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.run_kwargs = None

    def move(self, game_id: str, action: dict) -> dict:
        return self.responses.pop(0)

    def run(self, strategy, **kwargs):
        self.run_kwargs = kwargs
        self.move("game-from-run", {"decision": "yes"})

    def stats(self):
        return {"games": 1}


class MoveResultCaptureTests(unittest.TestCase):
    def test_every_move_response_is_appended_and_terminal_result_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "move_results.jsonl"
            _FakeClient.responses = [
                {"valid": True, "game_over": False},
                {"valid": True, "game_over": True, "result": {"payoff": 1.25, "rating": 1432}},
            ]
            client = capturing_client_class(_FakeClient)(api_key="test", move_result_log=path)

            first = client.move("g-1", {"decision": "yes"})
            second = client.move("g-1", {"decision": "yes"})
            rows = [json.loads(line) for line in path.read_text().splitlines()]

            self.assertFalse(first["game_over"])
            self.assertTrue(second["game_over"])
            self.assertEqual([row["game_id"] for row in rows], ["g-1", "g-1"])
            self.assertIsNone(rows[0]["result"])
            self.assertEqual(rows[1]["result"], {"payoff": 1.25, "rating": 1432})
            self.assertEqual(rows[1]["move_result"], second)
            self.assertEqual(client.move_result_counters, {"moves": 2, "terminal_results": 1, "log_errors": 0})

    def test_play_accepts_an_injected_client_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _FakeClient.responses = [
                {"valid": True, "game_over": True, "result": {"payoff": 0.5}},
            ]

            summary = play(
                "my_agents.jordan_strategic:MyAgent",
                output_dir=tmp,
                client_class=_FakeClient,
                api_key="test-key",
                max_games=1,
            )

            rows = [json.loads(line) for line in (Path(tmp) / "move_results.jsonl").read_text().splitlines()]
            self.assertEqual(rows[0]["game_id"], "game-from-run")
            self.assertEqual(rows[0]["result"]["payoff"], 0.5)
            self.assertEqual(summary["move_result_capture"]["terminal_results"], 1)
            self.assertEqual(summary["stats"], {"games": 1})
            self.assertIn("GET/backfill", summary["move_result_coverage_note"])

    def test_capture_failure_never_changes_move_response(self) -> None:
        _FakeClient.responses = [{"valid": True, "game_over": False}]
        client = capturing_client_class(_FakeClient)(
            api_key="test", move_result_log="/nonexistent-root/results.jsonl"
        )

        self.assertEqual(client.move("g", {}), {"valid": True, "game_over": False})


if __name__ == "__main__":
    unittest.main()
