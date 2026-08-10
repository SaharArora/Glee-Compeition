from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.schemas import EpisodeResult, to_jsonable
from glee_eval.experiments.hypotheses import generate_hypotheses, hypotheses_markdown
from glee_eval.experiments.matches import write_match_ledger
from glee_eval.probes.runner import run_probes
from glee_eval.search.adversarial import search_failures
from glee_eval.storage.trajectories import ensure_dir, write_json, write_jsonl
from glee_eval.tournament.runner import run_tournament


def _timestamp_name(agent_spec: str) -> str:
    safe_agent = agent_spec.replace(":", "_").replace(".", "_").replace("/", "_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{safe_agent}"


def _candidate_records_from_episodes(episodes: list[EpisodeResult]) -> list[dict[str, Any]]:
    records = []
    for episode in episodes:
        for decision in episode.decision_records:
            if decision.role != episode.scenario.candidate_role:
                continue
            records.append(
                {
                    "episode_id": episode.episode_id,
                    "scenario_id": episode.scenario.scenario_id,
                    "family": episode.scenario.game_family,
                    "role": episode.scenario.candidate_role,
                    "round": decision.round,
                    "state": decision.visible_state,
                    "candidate_action": decision.action,
                    "terminal_outcome": episode.terminal_outcome,
                    "candidate_payoff": episode.candidate_payoff,
                    "opponent_payoff": episode.opponent_payoff,
                    "regret": episode.metrics.get("regret"),
                    "opponent_archetype": episode.opponent_spec.archetype,
                    "opponent_parameters": episode.opponent_spec.parameters,
                }
            )
    return records


def _episode_summaries(episodes: list[EpisodeResult]) -> list[dict[str, Any]]:
    return [
        {
            "episode_id": episode.episode_id,
            "scenario": to_jsonable(episode.scenario),
            "opponent_spec": to_jsonable(episode.opponent_spec),
            "candidate_payoff": episode.candidate_payoff,
            "opponent_payoff": episode.opponent_payoff,
            "terminal_outcome": episode.terminal_outcome,
            "metrics": episode.metrics,
            "failure_diagnostics": to_jsonable(episode.failure_diagnostics),
        }
        for episode in episodes
    ]


def _failure_cases(episodes: list[EpisodeResult]) -> list[dict[str, Any]]:
    rows = []
    for episode in episodes:
        if episode.failure_diagnostics:
            for failure in episode.failure_diagnostics:
                rows.append({"episode_id": episode.episode_id, **to_jsonable(failure)})
        elif float(episode.metrics.get("regret", 0.0)) > 0:
            rows.append(
                {
                    "episode_id": episode.episode_id,
                    "failure_type": "REGRET_ONLY",
                    "scenario": to_jsonable(episode.scenario),
                    "candidate_payoff": episode.candidate_payoff,
                    "regret": episode.metrics.get("regret"),
                    "critical_round": episode.metrics.get("critical_round"),
                    "notes": "No discrete failure diagnostic fired, but regret was positive.",
                }
            )
    return rows


def write_learning_datasets(run_dir: Path, tournament_episodes: list[EpisodeResult], elite_episodes: list[EpisodeResult]) -> dict[str, str]:
    dataset_dir = ensure_dir(run_dir / "datasets")
    all_episodes = tournament_episodes + elite_episodes
    paths = {
        "state_action_outcome": str(write_jsonl(dataset_dir / "state_action_outcome.jsonl", _candidate_records_from_episodes(all_episodes))),
        "episode_summary": str(write_jsonl(dataset_dir / "episode_summary.jsonl", _episode_summaries(all_episodes))),
        "failure_cases": str(write_jsonl(dataset_dir / "failure_cases.jsonl", _failure_cases(all_episodes))),
    }
    return paths


def run_experiment(
    agent_spec: str,
    name: str | None = None,
    families: list[str] | None = None,
    games: int = 1000,
    seed: int = 42,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    probe_limit: int = 1000,
    search_population: int = 300,
    search_generations: int = 2,
    search_elite_frac: float = 0.05,
    search_families: list[str] | None = None,
    match_report_limit: int = 200,
    output_root: str | Path = "runs",
    skip_probes: bool = False,
    skip_search: bool = False,
) -> dict[str, Any]:
    families = families or ["bargaining", "negotiation", "persuasion"]
    search_families = search_families or families
    run_name = name or _timestamp_name(agent_spec)
    run_dir = ensure_dir(Path(output_root) / run_name)

    config = {
        "agent": agent_spec,
        "families": families,
        "games": games,
        "seed": seed,
        "data_dir": str(data_dir),
        "probe_limit": probe_limit,
        "search_population": search_population,
        "search_generations": search_generations,
        "search_elite_frac": search_elite_frac,
        "search_families": search_families,
        "match_report_limit": match_report_limit,
        "skip_probes": skip_probes,
        "skip_search": skip_search,
    }
    write_json(run_dir / "config.json", config)

    probe_summary = None
    if not skip_probes and (Path(data_dir) / "processed" / "events.jsonl").exists():
        probe_result = run_probes(
            agent_spec=agent_spec,
            data_dir=data_dir,
            limit=probe_limit,
            seed=seed,
            output_dir=run_dir / "probes",
        )
        probe_summary = probe_result["summary"]

    tournament_result = run_tournament(
        agent_spec=agent_spec,
        families=families,
        games=games,
        seed=seed,
        output_dir=run_dir / "tournament",
    )
    tournament_episodes = tournament_result["episodes"]

    elite_episodes: list[EpisodeResult] = []
    search_summaries: dict[str, Any] = {}
    if not skip_search:
        for family in search_families:
            search_result = search_failures(
                agent_spec=agent_spec,
                family=family,
                population=search_population,
                elite_frac=search_elite_frac,
                generations=search_generations,
                seed=seed,
                output_dir=run_dir / "search" / family,
            )
            elite_episodes.extend(search_result["elites"])
            search_summaries[family] = {
                "objective": search_result["objective"],
                "history": search_result["history"],
                "output_dir": search_result["output_dir"],
            }

    dataset_paths = write_learning_datasets(run_dir, tournament_episodes, elite_episodes)
    match_paths = write_match_ledger(
        run_dir,
        tournament_episodes,
        elite_episodes,
        max_report_rows=match_report_limit,
    )
    hypothesis_report = generate_hypotheses(tournament_episodes, elite_episodes)
    ensure_dir(run_dir / "hypotheses")
    write_json(run_dir / "hypotheses" / "hypotheses.json", hypothesis_report)
    (run_dir / "hypotheses" / "hypotheses.md").write_text(hypotheses_markdown(hypothesis_report), encoding="utf-8")

    manifest = {
        "run_dir": str(run_dir),
        "config": config,
        "probe_summary": probe_summary,
        "tournament_metrics": tournament_result["metrics"],
        "search_summaries": search_summaries,
        "dataset_paths": dataset_paths,
        "match_paths": match_paths,
        "hypothesis_paths": {
            "json": str(run_dir / "hypotheses" / "hypotheses.json"),
            "markdown": str(run_dir / "hypotheses" / "hypotheses.md"),
        },
    }
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run an end-to-end agent data-generation experiment.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--name")
    parser.add_argument("--families", default="bargaining,negotiation,persuasion")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--probe-limit", type=int, default=1000)
    parser.add_argument("--search-population", type=int, default=300)
    parser.add_argument("--search-generations", type=int, default=2)
    parser.add_argument("--search-elite-frac", type=float, default=0.05)
    parser.add_argument("--search-families", default=None)
    parser.add_argument("--match-report-limit", type=int, default=200)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--skip-probes", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    args = parser.parse_args(argv)

    manifest = run_experiment(
        agent_spec=args.agent,
        name=args.name,
        families=[part for part in args.families.split(",") if part],
        games=args.games,
        seed=args.seed,
        data_dir=args.data_dir,
        probe_limit=args.probe_limit,
        search_population=args.search_population,
        search_generations=args.search_generations,
        search_elite_frac=args.search_elite_frac,
        search_families=[part for part in args.search_families.split(",") if part] if args.search_families else None,
        match_report_limit=args.match_report_limit,
        output_root=args.output_root,
        skip_probes=args.skip_probes,
        skip_search=args.skip_search,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
