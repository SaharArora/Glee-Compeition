from __future__ import annotations

from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import parse_game_dir, terminal_for_game
from glee_eval.storage.trajectories import read_json, read_records, write_json


def validate_games(games: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    attempted = 0
    checked = 0
    for game in games:
        path = game.get("path")
        if not path:
            continue
        attempted += 1
        try:
            reparsed_game, _ = parse_game_dir(path)
            checked += 1
            if reparsed_game.get("terminal_outcome") != game.get("terminal_outcome"):
                mismatches.append(
                    {
                        "game_id": game.get("game_id"),
                        "path": path,
                        "stored": game.get("terminal_outcome"),
                        "recomputed": reparsed_game.get("terminal_outcome"),
                    }
                )
        except Exception as exc:
            mismatches.append({"game_id": game.get("game_id"), "path": path, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "games_attempted": attempted,
        "games_checked": checked,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:100],
        "payoff_reconstruction_accuracy": None if attempted == 0 else (attempted - len(mismatches)) / attempted,
    }


def validate_processed(data_dir: str | Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    games_path = Path(data_dir) / "processed" / "games.jsonl"
    games = read_records(games_path) if games_path.exists() else []
    report = validate_games(games)
    report_path = Path("reports") / "data_validation.json"
    existing: dict[str, Any] = {}
    if report_path.exists():
        try:
            payload = read_json(report_path)
            existing = payload if isinstance(payload, dict) else {}
        except Exception:
            existing = {}
    merged = {**existing, "payoff_validation": report}
    write_json(report_path, merged)
    return merged


def validate_rows(family: str, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    return terminal_for_game(family, rows, config)


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Validate processed GLEE records.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args(argv)
    print(json.dumps(validate_processed(args.data_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
