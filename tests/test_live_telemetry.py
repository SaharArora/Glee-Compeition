from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from glee_eval.live import fixtures
from glee_eval.live_telemetry import (
    FAMILIES,
    FROZEN_AGENT_NAME,
    FROZEN_AGENT_UUID,
    TelemetryRecorder,
    _canonical_bytes,
    build_configuration_manifest,
    capture_environment,
    capture_git_state,
    evaluate_stop_rules,
    launch_canary,
    official_scoring_capability,
    reconcile_batch,
)
from glee_eval.telemetry_audit import audit_batch


REPO = Path(__file__).resolve().parents[1]
API_SECRET = "glee_test_super_secret_literal"
HMAC_SECRET = "h" * 40


def _rechain(rows: list[dict]) -> list[dict]:
    previous = None
    for index, row in enumerate(rows, 1):
        row["sequence"] = index
        row["previous_event_sha256"] = previous
        row.pop("event_sha256", None)
        row["event_sha256"] = hashlib.sha256(_canonical_bytes(row)).hexdigest()
        previous = row["event_sha256"]
    return rows


class _OfflineCanaryClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.pending: list[dict] = []
        self.next_id = 0

    def stats(self):
        return {
            "agent": {"agent_id": FROZEN_AGENT_UUID, "name": FROZEN_AGENT_NAME},
            "active_games": 0,
            "note": f"must redact {self.api_key}",
        }

    def queue(self, family: str):
        self.next_id += 1
        template = next(game for game in fixtures.sample_games() if game["game_family"] == family)
        game = copy.deepcopy(template)
        game["game_id"] = f"offline-{family}-{self.next_id}"
        game["scenario_id"] = f"scenario-{family}-{self.next_id}"
        self.pending.append(game)

    def pending_games(self):
        games, self.pending = self.pending, []
        return games

    def _handle_game(self, strategy, game):
        action = strategy(game)
        return self.move(game["game_id"], action).get("game_over", False)

    def move(self, game_id: str, action: dict):
        return {
            "valid": True,
            "game_over": True,
            "result": {
                "payoff": 0.5,
                "official_percentile": 0.7,
                "official_game_rating": 2100.0,
                "official_rating_update": 3.0,
                "public_opponent_adjustment": 0.1,
            },
        }

    def game_state(self, game_id: str):
        return {"game_over": True, "result": {"payoff": 0.5, "official_game_rating": 2100.0}}

    def _leave_queue_quietly(self):
        return None


class _WrongIdentityClient(_OfflineCanaryClient):
    def stats(self):
        return {"agent": {"agent_id": "wrong", "name": "impostor"}, "active_games": 0}


class GitAndEnvironmentIdentityTests(unittest.TestCase):
    def test_dirty_digest_is_deterministic_and_changes_with_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            clean = capture_git_state(repo)
            self.assertFalse(clean["dirty"])
            tracked.write_text("changed\n")
            (repo / "new.txt").write_text("one\n")
            first = capture_git_state(repo)
            second = capture_git_state(repo)
            self.assertTrue(first["dirty"])
            self.assertEqual(first["dirty_digest"], second["dirty_digest"])
            (repo / "new.txt").write_text("two\n")
            self.assertNotEqual(first["dirty_digest"], capture_git_state(repo)["dirty_digest"])

    def test_secret_is_hmaced_and_never_serialized(self) -> None:
        captured = capture_environment({
            "GLEE_API_KEY": API_SECRET,
            "GLEE_TELEMETRY_HMAC_KEY": HMAC_SECRET,
        })
        serial = json.dumps(captured)
        self.assertNotIn(API_SECRET, serial)
        self.assertNotIn(HMAC_SECRET, serial)
        self.assertEqual(len(captured["variables"]["GLEE_API_KEY"]["value_hmac_sha256"]), 64)

    def test_secret_requires_independent_hmac_key(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HMAC_KEY"):
            capture_environment({"GLEE_API_KEY": API_SECRET})

    def test_frozen_configuration_rejects_optional_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "model.json"
            artifact.write_text("{}")
            env = {
                "GLEE_API_KEY": API_SECRET,
                "GLEE_TELEMETRY_HMAC_KEY": HMAC_SECRET,
                "GLEE_RESPONSE_MODEL": str(artifact),
            }
            with self.assertRaisesRegex(RuntimeError, "artifact variables absent"):
                build_configuration_manifest(
                    REPO, env=env, families=FAMILIES, per_family_games=1,
                    concurrency=3, allow_dirty=True,
                )


class CapabilityAndStopTests(unittest.TestCase):
    def test_scoring_capability_is_explicit_when_available_and_unavailable(self) -> None:
        found = official_scoring_capability({"result": {"official_game_rating": 2200, "percentile": 0.8}})
        self.assertEqual(found["game_rating"]["status"], "available")
        self.assertEqual(found["game_rating"]["value"], 2200)
        self.assertEqual(found["rating_update"]["status"], "unavailable")

    def test_missing_official_score_is_immediate_attribution_stop(self) -> None:
        row = {"game_id": "g", "family": "bargaining", "official_scoring": official_scoring_capability({})}
        result = evaluate_stop_rules([row], {})
        self.assertTrue(result["global_stop"])
        self.assertIn("official_per_game_rating_unavailable", result["reasons"])

    def test_low_ratings_trigger_prospective_family_and_global_stop(self) -> None:
        rows = []
        for family in FAMILIES:
            for index in range(30):
                rows.append({
                    "game_id": f"{family}-{index}", "family": family,
                    "official_scoring": {"game_rating": {"status": "available", "value": 1700.0}},
                })
        result = evaluate_stop_rules(rows, {})
        self.assertTrue(result["global_stop"])
        self.assertEqual(set(result["paused_families"]), set(FAMILIES))
        self.assertIn("pooled_upper_bound_below_1800", result["reasons"])


class OfflineIntegrationAndHostileAuditTests(unittest.TestCase):
    def _run(self, tmp: str) -> Path:
        out = Path(tmp) / "batch"
        report = launch_canary(
            output_dir=out,
            repo=REPO,
            client_class=_OfflineCanaryClient,
            env={"GLEE_API_KEY": API_SECRET, "GLEE_TELEMETRY_HMAC_KEY": HMAC_SECRET},
            per_family_games=1,
            concurrency=3,
            poll_interval=0,
            rehearsal=True,
        )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["family_terminal_counts"], {family: 1 for family in FAMILIES})
        return out

    def test_end_to_end_rehearsal_captures_required_fields_and_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(tmp)
            raw = b"".join(path.read_bytes() for path in out.iterdir())
            self.assertNotIn(API_SECRET.encode(), raw)
            self.assertNotIn(HMAC_SECRET.encode(), raw)
            rows = [json.loads(line) for line in (out / "telemetry.jsonl").read_text().splitlines()]
            terminals = [row for row in rows if row.get("event_type") == "move_result" and row.get("terminal")]
            self.assertEqual(len(terminals), 3)
            for row in terminals:
                self.assertIn(row["family"], FAMILIES)
                self.assertIsNotNone(row["scenario_id"])
                self.assertIsNotNone(row["role"])
                self.assertEqual(row["payoff"], 0.5)
                self.assertEqual(row["official_scoring"]["game_rating"]["status"], "available")

    def test_hostile_auditor_rejects_rehearsal_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(tmp)
            audit = audit_batch(
                out, expected_per_family=1, forbidden_secret_values=(API_SECRET, HMAC_SECRET)
            )
            self.assertFalse(audit["attributable"])
            self.assertIn("launch_tree_dirty", audit["errors"])

    def test_identity_mismatch_fails_before_queue_and_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "batch"
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                launch_canary(
                    output_dir=out, repo=REPO, client_class=_WrongIdentityClient,
                    env={"GLEE_API_KEY": API_SECRET, "GLEE_TELEMETRY_HMAC_KEY": HMAC_SECRET},
                    per_family_games=1, concurrency=3, poll_interval=0, rehearsal=True,
                )
            report = json.loads((out / "reconciliation.json").read_text())
            self.assertEqual(report["status"], "invalid")
            self.assertIn("preflight_failure", report["fatal_runtime_events"])
            self.assertEqual(report["unique_terminal_games"], 0)

    def test_hostile_auditor_passes_clean_synthetic_then_rejects_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(tmp)
            manifest_path = out / "launch_manifest.json"
            events_path = out / "telemetry.jsonl"
            manifest = json.loads(manifest_path.read_text())
            git_row = manifest["configuration"]["git"]
            git_row["dirty"] = False
            git_row["tracked_diff_sha256"] = hashlib.sha256(b"").hexdigest()
            git_row["untracked"] = []
            git_row["dirty_digest"] = hashlib.sha256(_canonical_bytes({
                "tracked_diff_sha256": hashlib.sha256(b"").hexdigest(), "untracked": []
            })).hexdigest()
            digest = hashlib.sha256(_canonical_bytes(manifest["configuration"])).hexdigest()
            manifest["configuration_sha256"] = digest
            manifest_path.write_bytes(_canonical_bytes(manifest))
            rows = [json.loads(line) for line in events_path.read_text().splitlines()]
            for row in rows:
                row["configuration_sha256"] = digest
            _rechain(rows)
            events_path.write_bytes(b"".join(_canonical_bytes(row) for row in rows))
            audit = audit_batch(out, expected_per_family=1)
            self.assertTrue(audit["attributable"], audit)

            terminal = next(row for row in rows if row.get("event_type") == "move_result" and row.get("terminal"))
            duplicate = dict(terminal)
            duplicate["sequence"] = len(rows) + 1
            duplicate["previous_event_sha256"] = rows[-1]["event_sha256"]
            duplicate.pop("event_sha256", None)
            duplicate["event_sha256"] = hashlib.sha256(_canonical_bytes(duplicate)).hexdigest()
            with events_path.open("ab") as handle:
                handle.write(_canonical_bytes(duplicate))
            hostile = audit_batch(out, expected_per_family=1)
            self.assertFalse(hostile["attributable"])
            self.assertIn("duplicate_terminal", hostile["errors"])

    def test_hostile_auditor_rejects_configuration_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(tmp)
            manifest_path = out / "launch_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["configuration"]["concurrency"] = 99
            manifest_path.write_bytes(_canonical_bytes(manifest))
            audit = audit_batch(out, expected_per_family=1)
            self.assertFalse(audit["attributable"])
            self.assertIn("configuration_digest_mismatch", audit["errors"])

    def test_reconciliation_detects_partial_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run(tmp)
            events_path = out / "telemetry.jsonl"
            rows = [json.loads(line) for line in events_path.read_text().splitlines()]
            removed = False
            kept = []
            for row in rows:
                if not removed and row.get("event_type") == "move_result" and row.get("terminal"):
                    removed = True
                    continue
                kept.append(row)
            _rechain(kept)
            events_path.write_bytes(b"".join(_canonical_bytes(row) for row in kept))
            report = reconcile_batch(out, write=False)
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["unique_terminal_games"], 2)

    def test_recorder_redacts_secret_literal_in_unexpected_payload_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            recorder = TelemetryRecorder(
                path, batch_id="b", configuration_sha256="c", secret_values=(API_SECRET,)
            )
            recorder.append("hostile", ordinary_note=f"echo:{API_SECRET}")
            self.assertNotIn(API_SECRET, path.read_text())


if __name__ == "__main__":
    unittest.main()
