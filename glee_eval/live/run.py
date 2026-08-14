"""CLI for playing live GLEE competition games, and for rehearsing without a key.

`--dry-run` replays synthetic game payloads shaped like the documented live schema
through the whole adapter without touching the network, so the plumbing can be
exercised before an API key exists. It is a rehearsal of *our* half of the
contract only: it cannot confirm that the server's real payloads match the
documented shapes, which is what the observation log is for.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from glee_eval.live.fixtures import sample_games
from glee_eval.live.strategy import build_strategy
from glee_eval.storage.trajectories import ensure_dir, write_json


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
) -> dict[str, Any]:
    """Queue and play live games. Requires GLEE_API_KEY in the environment."""

    try:
        from glee_sdk import GleeClient
    except ImportError as exc:  # pragma: no cover - depends on the local env
        raise SystemExit("glee-sdk is not installed. Run: python3 -m pip install glee-sdk") from exc

    api_key = os.getenv("GLEE_API_KEY")
    if not api_key:
        raise SystemExit(
            "GLEE_API_KEY is not set. Create an agent at https://glee-competition.com, "
            "then export the key in your shell: export GLEE_API_KEY=glee_..."
        )

    out = ensure_dir(output_dir)
    strategy = build_strategy(agent_spec, observation_log=out / "observations.jsonl")
    client = GleeClient(api_key=api_key)
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
        summary = strategy.summary()
        try:
            summary["stats"] = client.stats()
        except Exception as exc:  # noqa: BLE001
            summary["stats_error"] = str(exc)
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
