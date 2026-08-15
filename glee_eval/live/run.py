"""CLI for playing live GLEE competition games, and for rehearsing without a key.

`--dry-run` replays synthetic game payloads shaped like the documented live schema
through the whole adapter without touching the network, so the plumbing can be
exercised before an API key exists. It is a rehearsal of *our* half of the
contract only: it cannot confirm that the server's real payloads match the
documented shapes, which is what the observation log is for.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from glee_eval.live.fixtures import sample_games
from glee_eval.live.strategy import build_strategy
from glee_eval.storage.trajectories import ensure_dir, write_json

ClientT = TypeVar("ClientT")


def _path_setting(name: str) -> dict[str, Any]:
    raw = os.getenv(name)
    if not raw:
        return {"configured": False}
    path = Path(raw).expanduser().resolve()
    result: dict[str, Any] = {"configured": True, "path": str(path), "exists": path.is_file()}
    if path.is_file():
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _launch_manifest(agent_spec: str, families: list[str] | None, concurrency: int,
                     max_games: int | None, max_time: float | None) -> dict[str, Any]:
    """Record non-secret run inputs needed to reproduce which policy paths were active."""

    return {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "agent": agent_spec,
        "families": families,
        "concurrency": concurrency,
        "max_games": max_games,
        "max_time": max_time,
        "environment": {
            name: _path_setting(name)
            for name in ("GLEE_SUPPORT_INDEX", "GLEE_RESPONSE_MODEL", "GLEE_OPPONENT_POPULATION", "GLEE_CONFIG_CATALOGUE")
        },
    }


def capturing_client_class(base: type[ClientT]) -> type[ClientT]:
    """Add best-effort JSONL capture around a client's real ``move`` call.

    The SDK decides whether a game ended inside ``_handle_game`` from the mapping
    returned by ``move``.  Overriding that exact boundary records the same result
    without duplicating or replacing any SDK run-loop logic.
    """

    class MoveResultCapturingClient(base):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, move_result_log: str | Path | None = None, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self.move_result_log = Path(move_result_log) if move_result_log else None
            self._move_result_lock = threading.Lock()
            self._seen_game_ids: set[str] = set()
            self._terminal_game_ids: set[str] = set()
            self.move_result_counters = {
                "moves": 0, "terminal_results": 0, "backfill_attempts": 0,
                "backfill_terminal_results": 0, "backfill_errors": 0, "log_errors": 0,
            }
            if self.move_result_log:
                try:
                    self.move_result_log.parent.mkdir(parents=True, exist_ok=True)
                except Exception:  # noqa: BLE001 - result capture must never block a move
                    logging.getLogger("glee_eval.live").exception(
                        "Cannot create %s; continuing without move-result capture", self.move_result_log
                    )
                    self.move_result_log = None

        def move(self, game_id: str, action: dict[str, Any]) -> dict[str, Any]:
            response = super().move(game_id, action)
            record = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "game_id": game_id,
                "game_over": bool(response.get("game_over")) if isinstance(response, dict) else None,
                "result": response.get("result") if isinstance(response, dict) else None,
                "move_result": response,
            }
            with self._move_result_lock:
                self.move_result_counters["moves"] += 1
                self._seen_game_ids.add(game_id)
                if record["game_over"]:
                    self.move_result_counters["terminal_results"] += 1
                    self._terminal_game_ids.add(game_id)
                if self.move_result_log:
                    try:
                        with self.move_result_log.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
                    except Exception:  # noqa: BLE001 - logging must never change SDK behavior
                        self.move_result_counters["log_errors"] += 1
                        logging.getLogger("glee_eval.live").exception(
                            "Could not append move result for game %s", game_id
                        )
            return response

        def backfill_terminal_results(self) -> None:
            """Capture the final GET payload for games that ended after an opponent move."""

            for game_id in sorted(self._seen_game_ids - self._terminal_game_ids):
                self.move_result_counters["backfill_attempts"] += 1
                try:
                    response = self.game_state(game_id)
                    record = {
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "game_id": game_id,
                        "source": "game_state_backfill",
                        "game_over": response.get("game_over") if isinstance(response, dict) else None,
                        "result": response.get("result") if isinstance(response, dict) else None,
                        "move_result": response,
                    }
                    if record["game_over"] or record["result"] is not None:
                        self.move_result_counters["backfill_terminal_results"] += 1
                        self._terminal_game_ids.add(game_id)
                    if self.move_result_log:
                        with self._move_result_lock, self.move_result_log.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
                except Exception:  # noqa: BLE001 - backfill is evidence capture, never gameplay
                    self.move_result_counters["backfill_errors"] += 1
                    logging.getLogger("glee_eval.live").exception(
                        "Could not backfill terminal result for game %s", game_id
                    )

    MoveResultCapturingClient.__name__ = f"MoveResultCapturing{base.__name__}"
    return MoveResultCapturingClient


def dry_run(agent_spec: str, *, output_dir: str | Path = "reports/live", repeats: int = 1) -> dict[str, Any]:
    """Push every documented phase of every family through the adapter."""

    out = ensure_dir(output_dir)
    strategy = build_strategy(agent_spec, observation_log=out / "dry_run_observations.jsonl")
    results = []
    for _ in range(repeats):
        for game in sample_games():
            action = strategy(game)
            results.append(
                {
                    "family": game["game_family"],
                    "action_type": game["valid_actions"]["type"],
                    "action": action,
                }
            )
    summary = {"agent": agent_spec, "cases": len(results), **strategy.summary(), "actions": results}
    write_json(out / "dry_run.json", summary)
    return summary


def play(
    agent_spec: str,
    *,
    families: list[str] | None = None,
    concurrency: int = 6,
    max_games: int | None = None,
    max_time: float | None = None,
    poll_interval: float = 2.0,
    output_dir: str | Path = "reports/live",
    client_class: type[Any] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Queue and play live games. Requires GLEE_API_KEY in the environment."""

    if client_class is None:
        try:
            from glee_sdk import GleeClient
        except ImportError as exc:  # pragma: no cover - depends on the local env
            raise SystemExit("glee-sdk is not installed. Run: python3 -m pip install glee-sdk") from exc
        client_class = GleeClient

    api_key = api_key or os.getenv("GLEE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GLEE_API_KEY is not set. Create an agent at https://glee-competition.com, "
            "then export the key in your shell: export GLEE_API_KEY=glee_..."
        )

    out = ensure_dir(output_dir)
    write_json(out / "launch_manifest.json", _launch_manifest(agent_spec, families, concurrency, max_games, max_time))
    strategy = build_strategy(agent_spec, observation_log=out / "observations.jsonl")
    CapturingClient = capturing_client_class(client_class)
    client = CapturingClient(api_key=api_key, move_result_log=out / "move_results.jsonl")
    logging.getLogger("glee_sdk").setLevel(logging.INFO)

    try:
        client.run(
            strategy,
            game_families=families,
            concurrency=concurrency,
            max_games=max_games,
            max_time=max_time,
            poll_interval=poll_interval,
        )
    finally:
        # Written even on Ctrl+C, since that is a normal way to stop a long run.
        client.backfill_terminal_results()
        summary = strategy.summary()
        try:
            summary["stats"] = client.stats()
        except Exception as exc:  # noqa: BLE001
            summary["stats_error"] = str(exc)
        summary["move_result_capture"] = dict(client.move_result_counters)
        summary["move_result_coverage_note"] = (
            "Captures every submitted-move response, then GET-backfills games without a "
            "terminal move response. Inspect capture counters; never assume complete coverage."
        )
        write_json(out / "run_summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Play GLEE competition games live, or rehearse the adapter.")
    parser.add_argument("--agent", default="my_agents.jordan_strategic:MyAgent")
    parser.add_argument("--dry-run", action="store_true", help="Exercise the adapter with synthetic payloads, no network.")
    parser.add_argument("--families", default=None, help="Comma-separated subset; default is all three.")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--max-time", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--output-dir", default="reports/live")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stdout)

    if args.dry_run:
        summary = dry_run(args.agent, output_dir=args.output_dir)
        print(json.dumps({k: v for k, v in summary.items() if k != "actions"}, indent=2, sort_keys=True))
        for row in summary["actions"]:
            print(f"  {row['family']:12s} {row['action_type']:22s} -> {json.dumps(row['action'], sort_keys=True)}")
        return

    play(
        args.agent,
        families=[part for part in args.families.split(",") if part] if args.families else None,
        concurrency=args.concurrency,
        max_games=args.max_games,
        max_time=args.max_time,
        poll_interval=args.poll_interval,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
