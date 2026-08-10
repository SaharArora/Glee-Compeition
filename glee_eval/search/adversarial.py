from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.data.schemas import EpisodeResult, to_jsonable
from glee_eval.population.sampler import sample_scenario
from glee_eval.storage.trajectories import write_json, write_jsonl
from glee_eval.tournament.metrics import summarize_episodes
from glee_eval.tournament.runner import run_episode


def _score(episode: EpisodeResult, objective: str) -> float:
    if objective == "minimum_payoff":
        return -episode.candidate_payoff
    if objective == "maximum_regret":
        return float(episode.metrics.get("regret", 0.0))
    if objective == "trade_failure":
        return 1.0 if not episode.metrics.get("trade_or_sale") else 0.0
    if objective == "ir_violation":
        return float(episode.metrics.get("ir_violation", 0.0))
    if objective == "format_failure":
        return float(episode.metrics.get("malformed_response", 0.0))
    raise ValueError(f"Unsupported objective: {objective}")


def search_failures(
    agent_spec: str = "heuristic",
    family: str = "negotiation",
    population: int = 200,
    elite_frac: float = 0.05,
    generations: int = 3,
    seed: int = 42,
    objective: str = "maximum_regret",
    output_dir: str | Path = "reports/search_failures",
) -> dict[str, Any]:
    rng = random.Random(seed)
    agent = load_agent(agent_spec, seed=seed)
    elites: list[EpisodeResult] = []
    history: list[dict[str, Any]] = []
    for generation in range(generations):
        episodes: list[EpisodeResult] = []
        for _ in range(population):
            if generation and elites and rng.random() < 0.5:
                base = rng.choice(elites).scenario
                scenario = sample_scenario(family, seed=base.seed + rng.randrange(1, 10_000), candidate_role=base.candidate_role)
            else:
                scenario = sample_scenario(family, seed=rng.randrange(10**9))
            episodes.append(run_episode(scenario, agent))
        ranked = sorted(episodes, key=lambda ep: _score(ep, objective), reverse=True)
        keep = max(1, int(population * elite_frac))
        elites = ranked[:keep]
        history.append(
            {
                "generation": generation,
                "best_score": _score(elites[0], objective),
                "best_candidate_payoff": elites[0].candidate_payoff,
                "best_regret": elites[0].metrics.get("regret"),
                "summary": summarize_episodes(episodes),
            }
        )
    out = Path(output_dir)
    write_jsonl(out / "elite_episodes.jsonl", [to_jsonable(ep) for ep in elites])
    write_json(out / "summary.json", {"objective": objective, "history": history, "elite_count": len(elites)})
    return {"objective": objective, "history": history, "elites": elites, "output_dir": str(out)}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Search for hard synthetic GLEE scenarios.")
    parser.add_argument("--agent", default="heuristic")
    parser.add_argument("--family", default="negotiation")
    parser.add_argument("--population", type=int, default=200)
    parser.add_argument("--elite-frac", type=float, default=0.05)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--objective", default="maximum_regret")
    parser.add_argument("--output-dir", default="reports/search_failures")
    args = parser.parse_args(argv)
    result = search_failures(
        agent_spec=args.agent,
        family=args.family,
        population=args.population,
        elite_frac=args.elite_frac,
        generations=args.generations,
        seed=args.seed,
        objective=args.objective,
        output_dir=args.output_dir,
    )
    print(json.dumps({"objective": result["objective"], "history": result["history"], "output_dir": result["output_dir"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

