from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from glee_eval.live.run import capturing_client_class, play


class _FakeClient:
    responses: list[dict] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.run_kwargs = None
        self.states = {}

    def move(self, game_id: str, action: dict) -> dict:
        return self.responses.pop(0)

    def run(self, strategy, **kwargs):
        self.run_kwargs = kwargs
        self.move("game-from-run", {"decision": "yes"})

    def stats(self):
        return {"games": 1}

    def game_state(self, game_id: str):
        return self.states.get(game_id, {"game_over": False})


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
            self.assertEqual(client.move_result_counters["moves"], 2)
            self.assertEqual(client.move_result_counters["terminal_results"], 1)

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
            self.assertIn("GET-backfills", summary["move_result_coverage_note"])
            manifest = json.loads((Path(tmp) / "launch_manifest.json").read_text())
            self.assertFalse(manifest["environment"]["GLEE_SUPPORT_INDEX"]["configured"])

    def test_launch_manifest_records_support_index_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            support = Path(tmp) / "support.json"
            support.write_text('{"buckets": {}}')
            _FakeClient.responses = [{"valid": True, "game_over": True, "result": {"payoff": 0.5}}]
            with patch.dict(os.environ, {"GLEE_SUPPORT_INDEX": str(support)}, clear=False):
                play("my_agents.jordan_strategic:MyAgent", output_dir=tmp,
                     client_class=_FakeClient, api_key="test-key", max_games=1)
            setting = json.loads((Path(tmp) / "launch_manifest.json").read_text())["environment"]["GLEE_SUPPORT_INDEX"]
            self.assertTrue(setting["configured"])
            self.assertTrue(setting["exists"])
            self.assertEqual(len(setting["sha256"]), 64)

    def test_opponent_ended_game_is_backfilled_after_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _FakeClient.responses = [{"valid": True, "game_over": False}]

            class OpponentEndedClient(_FakeClient):
                def game_state(self, game_id: str):
                    return {"game_over": True, "result": {"payoff": 0.75}}

            summary = play("my_agents.jordan_strategic:MyAgent", output_dir=tmp,
                           client_class=OpponentEndedClient, api_key="test-key", max_games=1)
            rows = [json.loads(line) for line in (Path(tmp) / "move_results.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["source"], "game_state_backfill")
            self.assertEqual(rows[-1]["result"]["payoff"], 0.75)
            self.assertEqual(summary["move_result_capture"]["backfill_terminal_results"], 1)

    def test_capture_failure_never_changes_move_response(self) -> None:
        _FakeClient.responses = [{"valid": True, "game_over": False}]
        client = capturing_client_class(_FakeClient)(
            api_key="test", move_result_log="/nonexistent-root/results.jsonl"
        )

        self.assertEqual(client.move("g", {}), {"valid": True, "game_over": False})


if __name__ == "__main__":
    unittest.main()
