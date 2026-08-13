from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path
from statistics import mean
from typing import Any

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.data.dataset_audit import support_lookup
from glee_eval.data.schemas import AgentAction, EpisodeResult, GameState, Scenario, to_jsonable
from glee_eval.population.sampler import sample_scenario
from glee_eval.simulate.coverage_gate import CoverageGate
from glee_eval.storage.trajectories import ensure_dir, write_json, write_jsonl
from glee_eval.tournament.metrics import summarize_episodes
from glee_eval.tournament.runner import run_episode


TRIGGERS = {
    "rare_type",
    "counterfactual",
    "adversarial",
    "long_horizon",
    "policy_optimization",
}


class TargetedSimulationDispatcher:
    """Auditable gate for all experiment-time synthetic simulation."""

    def __init__(
        self,
        *,
        agent_spec: str,
        support_index: dict[str, Any] | None,
        audit_report: dict[str, Any] | None,
        seed: int,
        ledger_path: str | Path,
        coverage_threshold: float = 0.35,
        max_counterfactual_dispatches: int = 3,
        counterfactual_games: int = 25,
        counterfactual_output_root: str | Path | None = None,
    ):
        self.agent_spec = agent_spec
        self.support_index = support_index or {"buckets": {}}
        self.audit_report = audit_report or {}
        self.seed = seed
        self.ledger_path = Path(ledger_path)
        self.entries: list[dict[str, Any]] = []
        self._counterfactual_active = False
        self.coverage_gate = CoverageGate(
            self.support_index,
            threshold=coverage_threshold,
            dispatcher=self,
            max_dispatches=max_counterfactual_dispatches,
            games_per_dispatch=counterfactual_games,
            output_root=counterfactual_output_root or (self.ledger_path.parent / "counterfactual"),
        )

    def build_agent(self) -> Any:
        """Load the candidate agent and hand it the run's shared coverage gate.

        Injection is duck-typed: agents that do not implement
        `attach_coverage_gate` are loaded unchanged.
        """

        agent = load_agent(self.agent_spec, seed=self.seed)
        attach = getattr(agent, "attach_coverage_gate", None)
        if callable(attach):
            attach(self.coverage_gate)
        return agent

    def _record(self, entry: dict[str, Any]) -> None:
        entry = {"schema_version": 1, **entry}
        self.entries.append(entry)
        write_jsonl(self.ledger_path, self.entries)

    def _tag(self, scenario: Scenario, trigger: str, reason: str, gap: dict[str, Any]) -> Scenario:
        if trigger not in TRIGGERS:
            raise ValueError(f"Unsupported simulation trigger: {trigger}")
        metadata = dict(scenario.metadata)
        metadata["simulation"] = {
            "trigger": trigger,
            "reason": reason,
            "gap": gap,
            "dispatcher_seed": self.seed,
        }
        return replace(scenario, source="targeted_simulation", metadata=metadata)

    def policy_optimization_simulation(
        self,
        *,
        families: list[str],
        games: int,
        output_dir: str | Path,
    ) -> dict[str, Any]:
        reason = "Evaluate the current policy through the local compact synthetic runner after empirical audit artifacts are available."
        gap = {
            "real_data_available": bool(self.support_index.get("buckets")),
            "note": "OPE-lite placeholder uses local episodes; future variants can swap in pure response-surface rollouts behind this dispatcher.",
        }
        rng = random.Random(self.seed)
        agent = self.build_agent()
        episodes = []
        for _ in range(games):
            family = rng.choice(families)
            scenario = self._tag(sample_scenario(family, seed=rng.randrange(10**9)), "policy_optimization", reason, gap)
            episodes.append(run_episode(scenario, agent))
        metrics = summarize_episodes(episodes)
        out = ensure_dir(output_dir)
        write_jsonl(out / "episodes.jsonl", [to_jsonable(ep) for ep in episodes])
        write_json(out / "metrics.json", metrics)
        self._record(
            {
                "trigger": "policy_optimization",
                "status": "ran",
                "reason": reason,
                "gap": gap,
                "episodes": len(episodes),
                "output_dir": str(out),
                "changed_recommended_action": None,
            }
        )
        return {"metrics": metrics, "episodes": episodes, "output_dir": str(out)}

    def adversarial_simulation(
        self,
        *,
        family: str,
        population: int,
        elite_frac: float,
        generations: int,
        objective: str,
        output_dir: str | Path,
        known_failure_patterns: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        reason = "Explicit red-team pass over known high-regret and failure-search patterns."
        gap = {
            "family": family,
            "objective": objective,
            "known_failure_patterns": known_failure_patterns or [],
        }
        from glee_eval.search.adversarial import search_failures

        result = search_failures(
            agent_spec=self.agent_spec,
            family=family,
            population=population,
            elite_frac=elite_frac,
            generations=generations,
            seed=self.seed,
            objective=objective,
            output_dir=output_dir,
            simulation_trigger="adversarial",
            simulation_reason=reason,
            simulation_gap=gap,
        )
        self._record(
            {
                "trigger": "adversarial",
                "status": "ran",
                "reason": reason,
                "gap": gap,
                "episodes": len(result.get("elites", [])),
                "output_dir": result.get("output_dir"),
                "changed_recommended_action": None,
            }
        )
        return result

    def rare_type_simulation(
        self,
        *,
        family: str,
        config: dict[str, Any],
        role: str,
        action: AgentAction | dict[str, Any],
        state: GameState,
        threshold: float = 0.25,
        games: int = 25,
        output_dir: str | Path = "reports/rare_type_simulation",
    ) -> dict[str, Any]:
        coverage = support_lookup(family, config, role, action, state, support_index=self.support_index)
        if coverage["coverage_score"] >= threshold:
            self._record({"trigger": "rare_type", "status": "skipped", "reason": "Coverage above threshold.", "gap": coverage, "episodes": 0})
            return {"skipped": True, "coverage": coverage, "episodes": []}
        return self._scenario_gap_simulation(
            trigger="rare_type",
            reason="Observed behavior segment is under-covered in the empirical support index.",
            gap=coverage,
            family=family,
            role=role,
            games=games,
            output_dir=output_dir,
        )

    def counterfactual_available(self) -> bool:
        """False while a counterfactual simulation is already running.

        Agents inside a counterfactual simulation reach the same coverage gate,
        so without this the first out-of-support decision would recurse forever.
        """

        return not self._counterfactual_active

    def counterfactual_simulation(
        self,
        *,
        family: str,
        config: dict[str, Any],
        role: str,
        action: AgentAction | dict[str, Any],
        state: GameState,
        threshold: float = 0.35,
        games: int = 25,
        output_dir: str | Path = "reports/counterfactual_simulation",
    ) -> dict[str, Any]:
        coverage = support_lookup(family, config, role, action, state, support_index=self.support_index)
        if not self.counterfactual_available():
            self._record({"trigger": "counterfactual", "status": "skipped", "reason": "Already inside a counterfactual simulation.", "gap": coverage, "episodes": 0})
            return {"skipped": True, "coverage": coverage, "episodes": []}
        if coverage["coverage_score"] >= threshold:
            self._record({"trigger": "counterfactual", "status": "skipped", "reason": "Action was inside empirical support.", "gap": coverage, "episodes": 0})
            return {"skipped": True, "coverage": coverage, "episodes": []}
        self._counterfactual_active = True
        try:
            return self._scenario_gap_simulation(
                trigger="counterfactual",
                reason="Requested action lies outside reliable empirical support.",
                gap=coverage,
                family=family,
                role=role,
                games=games,
                output_dir=output_dir,
            )
        finally:
            self._counterfactual_active = False

    def long_horizon_simulation(
        self,
        *,
        family: str,
        min_horizon: int,
        games: int = 25,
        output_dir: str | Path = "reports/long_horizon_simulation",
    ) -> dict[str, Any]:
        turns = ((self.audit_report.get("dataset_size") or {}).get("turns_per_game") or {})
        observed_max = turns.get("max")
        if observed_max is not None and float(observed_max) >= min_horizon:
            gap = {"observed_max_turns": observed_max, "requested_min_horizon": min_horizon}
            self._record({"trigger": "long_horizon", "status": "skipped", "reason": "Observed data already reaches requested horizon.", "gap": gap, "episodes": 0})
            return {"skipped": True, "gap": gap, "episodes": []}
        gap = {"observed_max_turns": observed_max, "requested_min_horizon": min_horizon}
        return self._scenario_gap_simulation(
            trigger="long_horizon",
            reason="Requested horizon exceeds empirical turn-depth coverage.",
            gap=gap,
            family=family,
            role=None,
            games=games,
            output_dir=output_dir,
        )

    def _scenario_gap_simulation(
        self,
        *,
        trigger: str,
        reason: str,
        gap: dict[str, Any],
        family: str,
        role: str | None,
        games: int,
        output_dir: str | Path,
    ) -> dict[str, Any]:
        rng = random.Random(self.seed + len(self.entries) + 1000)
        agent = self.build_agent()
        episodes = [
            run_episode(self._tag(sample_scenario(family, seed=rng.randrange(10**9), candidate_role=role), trigger, reason, gap), agent)
            for _ in range(games)
        ]
        out = ensure_dir(output_dir)
        metrics = summarize_episodes(episodes)
        write_jsonl(out / "episodes.jsonl", [to_jsonable(ep) for ep in episodes])
        write_json(out / "metrics.json", metrics)
        self._record(
            {
                "trigger": trigger,
                "status": "ran",
                "reason": reason,
                "gap": gap,
                "episodes": len(episodes),
                "mean_payoff": mean([episode.candidate_payoff for episode in episodes]) if episodes else None,
                "output_dir": str(out),
                "changed_recommended_action": None,
            }
        )
        return {"skipped": False, "gap": gap, "metrics": metrics, "episodes": episodes, "output_dir": str(out)}
