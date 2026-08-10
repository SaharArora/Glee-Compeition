from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.stats import compute_empirical_stats
from glee_eval.storage.trajectories import read_records, write_json
from glee_eval.tournament.runner import run_tournament


def calibrate_population(
    games: int = 300,
    seed: int = 42,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports",
) -> dict[str, Any]:
    historical_events = read_records(Path(data_dir) / "processed" / "events.jsonl")
    historical_games = read_records(Path(data_dir) / "processed" / "games.jsonl")
    historical = compute_empirical_stats(historical_events, historical_games) if historical_events and historical_games else {}
    synthetic_result = run_tournament(agent_spec="heuristic", games=games, seed=seed, output_dir=Path(output_dir) / "population_synthetic")
    synthetic_metrics = synthetic_result["metrics"]
    report = {
        "historical_available": bool(historical),
        "historical_dataset": historical.get("dataset") if historical else None,
        "synthetic_games": games,
        "synthetic_metrics": synthetic_metrics,
        "coverage_notes": [
            "This baseline report compares major aggregate summaries. Distributional support checks can be expanded family-by-family as more reference policies are added.",
            "Synthetic population is intentionally parameterized and inspectable rather than claimed to perfectly model GLEE opponents.",
        ],
    }
    out = Path(output_dir)
    write_json(out / "population_coverage.json", report)
    html = "<html><body><h1>Population Coverage</h1><pre>" + json.dumps(report, indent=2, sort_keys=True) + "</pre></body></html>"
    (out / "population_coverage.html").write_text(html, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Compare synthetic population behavior with historical summaries.")
    parser.add_argument("--games", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)
    print(json.dumps(calibrate_population(args.games, args.seed, args.data_dir, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

