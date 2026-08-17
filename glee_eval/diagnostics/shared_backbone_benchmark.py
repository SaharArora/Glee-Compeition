"""Bounded paired benchmark of Jordan and the frozen Factorial00 economic core."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from glee_eval.experiments.ab import run_paired_ab
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.opponent_fit import OpponentPopulation
from glee_eval.storage.trajectories import write_json, write_jsonl
from my_agents.jordan_strategic import MyAgent
from research.CANDIDATES.wave3_factorial_agents import Factorial00Agent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_benchmark(
    *,
    population_path: str | Path,
    catalogue_path: str | Path,
    response_model_path: str | Path,
    response_model_sha256: str,
    support_index_path: str | Path,
    support_index_sha256: str,
    output_dir: str | Path,
    games: int = 900,
    seed: int = 20260816,
) -> dict[str, Any]:
    population_path = Path(population_path)
    catalogue_path = Path(catalogue_path)
    population_file = population_path / "opponent_population.json" if population_path.is_dir() else population_path
    catalogue_file = catalogue_path / "config_catalogue.json" if catalogue_path.is_dir() else catalogue_path
    population = OpponentPopulation.load(population_file)
    catalogue = ConfigCatalogue.load(catalogue_file)
    if population is None or catalogue is None:
        raise FileNotFoundError("Benchmark requires both frozen evaluator artifacts")
    provenance = {
        "opponent_population": {"path": str(population_file.resolve()), "sha256": _sha256(population_file), "model_b": False},
        "config_catalogue": {"path": str(catalogue_file.resolve()), "sha256": _sha256(catalogue_file)},
        "response_model": {"path": str(Path(response_model_path).resolve()), "sha256": response_model_sha256},
        "support_index": {"path": str(Path(support_index_path).resolve()), "sha256": support_index_sha256},
    }
    observations = run_paired_ab(
        lambda: MyAgent(seed=7),
        lambda: Factorial00Agent(
            seed=7,
            response_model_path=response_model_path,
            response_model_sha256=response_model_sha256,
            support_index_path=support_index_path,
            support_index_sha256=support_index_sha256,
        ),
        families=["bargaining", "negotiation", "persuasion"],
        games=games,
        seed=seed,
        population=population,
        catalogue=catalogue,
        artifact_provenance=provenance,
    )
    rows = [{
        "key": row.key,
        "jordan_payoff": row.baseline,
        "factorial00_payoff": row.candidate,
        "factorial00_minus_jordan": row.difference,
        **row.subgroups,
    } for row in observations]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["family"]), str(row["candidate_role"]))].append(row)

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        differences = [float(row["factorial00_minus_jordan"]) for row in group]
        return {
            "n": len(group),
            "mean_jordan": mean(float(row["jordan_payoff"]) for row in group),
            "mean_factorial00": mean(float(row["factorial00_payoff"]) for row in group),
            "mean_difference": mean(differences),
            "wins": sum(value > 1e-12 for value in differences),
            "losses": sum(value < -1e-12 for value in differences),
            "ties": sum(abs(value) <= 1e-12 for value in differences),
        }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "observations.jsonl", rows)
    summary = {
        "schema": "glee.wave5b.shared_backbone_benchmark.v1",
        "evidence_class": "bounded_offline_architecture_diagnostic_not_promotion",
        "games": games,
        "seed": seed,
        "families": ["bargaining", "negotiation", "persuasion"],
        "baseline": "my_agents.jordan_strategic:MyAgent",
        "candidate": "research.CANDIDATES.wave3_factorial_agents:Factorial00Agent",
        "provenance": provenance,
        "overall": summarize(rows),
        "by_family_role": {
            f"{family}:{role}": summarize(group)
            for (family, role), group in sorted(grouped.items())
        },
        "config_regimes": dict(Counter(str(row["config_regime"]) for row in rows)),
        "model_b_used": False,
        "promotion_authorized": False,
        "factorial_treatment_effect_estimated": False,
    }
    write_json(out / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", required=True)
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--response-model", required=True)
    parser.add_argument("--response-model-sha256", required=True)
    parser.add_argument("--support-index", required=True)
    parser.add_argument("--support-index-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--games", type=int, default=900)
    parser.add_argument("--seed", type=int, default=20260816)
    args = parser.parse_args(argv)
    result = run_benchmark(
        population_path=args.population,
        catalogue_path=args.catalogue,
        response_model_path=args.response_model,
        response_model_sha256=args.response_model_sha256,
        support_index_path=args.support_index,
        support_index_sha256=args.support_index_sha256,
        output_dir=args.output_dir,
        games=args.games,
        seed=args.seed,
    )
    print(json.dumps(result["overall"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
