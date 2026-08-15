"""Run a paired A/B between two agent configurations and gate it on the criteria.

Pairing is on the scenario: both arms play the identical scenario, so the
difference is the change and not the draw. Unpaired comparisons are what produced
the over-confident findings `promotion.py` exists to prevent.

Subgroup labels are attached here rather than in the gate, because what counts as
a "config regime" is family-specific: whether a negotiation has gains from trade,
whether a bargaining game has symmetric discounting, and so on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.schemas import GameState
from glee_eval.experiments.promotion import Observation, PromotionCriteria, evaluate_promotion, verdict_markdown
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.opponent_fit import OpponentPopulation
from glee_eval.population.sampler import sample_scenario
from glee_eval.storage.trajectories import ensure_dir, write_json, write_jsonl
from glee_eval.tournament.runner import run_episode


def config_regime(family: str, config: dict[str, Any]) -> str:
    """A coarse, interpretable label for the kind of game this configuration is."""

    if family == "bargaining":
        delta_1 = as_float(config.get("delta_1"))
        delta_2 = as_float(config.get("delta_2"))
        symmetry = "unknown"
        if delta_1 is not None and delta_2 is not None:
            symmetry = "symmetric" if abs(delta_1 - delta_2) < 1e-9 else ("p1_patient" if delta_1 > delta_2 else "p2_patient")
        return f"rounds={config.get('max_rounds')}|{symmetry}"
    if family == "negotiation":
        seller = as_float(config.get("seller_value"))
        buyer = as_float(config.get("buyer_value"))
        zone = "unknown"
        if seller is not None and buyer is not None:
            zone = "gains_from_trade" if buyer > seller else "no_trade_zone"
        return f"rounds={config.get('max_rounds')}|{zone}"
    if family == "persuasion":
        # `total_rounds` and `p` alone collapsed real persuasion into two regimes,
        # too few for the gate to judge concentration. The two axes that actually
        # divide the family are whether the buyer has memory and whether the seller
        # signals in free text -- both close to 50/50 in the released data, and both
        # strategically central.
        p = as_float(config.get("p"))
        prior = "unknown" if p is None else ("low_prior" if p < 0.5 else "high_prior")
        memory = "myopic" if config.get("is_myopic") else "persistent"
        channel = str(config.get("seller_message_type") or "unknown")
        return f"{memory}|{channel}|{prior}"
    return "unknown"


def negotiation_collapsed_margin_window(state: GameState, baseline: CandidateAgent) -> bool:
    """Whether the baseline is about to construct a zero-margin-only offer.

    This reads only the baseline pre-offer state. With buyer_value <=
    seller_value, the old seller clip is [seller, seller] and the old buyer clip
    is [buyer, buyer], so either role can construct only its reservation value.
    """

    if state.game_family != "negotiation" or state.valid_action_schema.get("kind") != "offer":
        return False
    beliefs_fn = getattr(baseline, "_negotiation_beliefs", None)
    if not callable(beliefs_fn):
        return False
    beliefs = beliefs_fn(state)
    seller = as_float(beliefs.get("seller_value"))
    buyer = as_float(beliefs.get("buyer_value"))
    return seller is not None and buyer is not None and buyer <= seller


def run_paired_ab(
    baseline_factory: Callable[[], CandidateAgent],
    candidate_factory: Callable[[], CandidateAgent],
    *,
    families: list[str],
    games: int,
    seed: int = 4242,
    population: OpponentPopulation | None = None,
    catalogue: ConfigCatalogue | None = None,
    baseline_state_predicates: dict[str, Callable[[GameState, CandidateAgent], bool]] | None = None,
) -> list[Observation]:
    """Play both arms over the same scenarios and return paired outcomes."""

    baseline = baseline_factory()
    candidate = candidate_factory()
    observations: list[Observation] = []
    for index in range(games):
        family = families[index % len(families)]
        scenario = sample_scenario(family, seed=seed + index, population=population, catalogue=catalogue)
        base_episode = run_episode(scenario, baseline)
        cand_episode = run_episode(scenario, candidate)
        predicate_results: dict[str, bool] = {}
        for name, predicate in (baseline_state_predicates or {}).items():
            predicate_results[name] = any(
                predicate(GameState(**record.visible_state), baseline)
                for record in base_episode.decision_records
            )
        observations.append(
            Observation(
                key=f"{family}:{scenario.scenario_id}:{scenario.candidate_role}",
                baseline=base_episode.candidate_payoff,
                candidate=cand_episode.candidate_payoff,
                subgroups={
                    "family": family,
                    "opponent_archetype": str(scenario.opponent_spec.get("archetype")),
                    "config_regime": config_regime(family, scenario.public_parameters),
                    "candidate_role": scenario.candidate_role,
                },
                branch_predicates=predicate_results,
            )
        )
    return observations


def gate_observations(
    observations: list[Observation],
    *,
    change: str,
    output_dir: str | Path,
    evaluated_on_holdout: bool,
    holdout_description: str | None = None,
    criteria: PromotionCriteria | None = None,
) -> dict[str, Any]:
    verdict = evaluate_promotion(
        observations,
        criteria=criteria,
        change=change,
        evaluated_on_holdout=evaluated_on_holdout,
        holdout_description=holdout_description,
    )
    out = ensure_dir(output_dir)
    write_jsonl(
        out / "promotion_observations.jsonl",
        [
            {
                "key": o.key,
                "baseline": o.baseline,
                "candidate": o.candidate,
                "difference": o.difference,
                **o.subgroups,
                "branch_predicates": o.branch_predicates,
            }
            for o in observations
        ],
    )
    write_json(out / "promotion_verdict.json", verdict)
    (out / "promotion_verdict.md").write_text(verdict_markdown(verdict), encoding="utf-8")
    return verdict


def main(argv: list[str] | None = None) -> None:
    import argparse

    from glee_eval.adapters.candidate_agent import load_agent

    parser = argparse.ArgumentParser(description="Gate a paired A/B against the promotion criteria.")
    parser.add_argument("--observations", help="Existing promotion_observations.jsonl to re-gate.")
    parser.add_argument("--baseline-agent", default="my_agents.jordan_strategic:MyAgent")
    parser.add_argument("--candidate-agent", default="my_agents.jordan_strategic:MyAgent")
    parser.add_argument("--change", default="unnamed change")
    parser.add_argument("--families", default="bargaining,negotiation,persuasion")
    parser.add_argument("--games", type=int, default=600)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--opponent-population", default=None)
    parser.add_argument("--config-catalogue", default=None)
    parser.add_argument("--output-dir", default="reports/promotion")
    parser.add_argument("--holdout", action="store_true", help="Assert this evaluation used withheld data.")
    parser.add_argument("--holdout-description", default=None)
    args = parser.parse_args(argv)

    if args.observations:
        rows = [json.loads(line) for line in Path(args.observations).read_text(encoding="utf-8").splitlines() if line.strip()]
        observations = [
            Observation(
                key=row["key"],
                baseline=float(row["baseline"]),
                candidate=float(row["candidate"]),
                subgroups={
                    k: v
                    for k, v in row.items()
                    if k not in {"key", "baseline", "candidate", "difference", "branch_predicates"}
                },
                branch_predicates={str(k): bool(v) for k, v in (row.get("branch_predicates") or {}).items()},
            )
            for row in rows
        ]
    else:
        observations = run_paired_ab(
            lambda: load_agent(args.baseline_agent, seed=7),
            lambda: load_agent(args.candidate_agent, seed=7),
            families=[part for part in args.families.split(",") if part],
            games=args.games,
            seed=args.seed,
            population=OpponentPopulation.load(args.opponent_population),
            catalogue=ConfigCatalogue.load(args.config_catalogue),
        )

    verdict = gate_observations(
        observations,
        change=args.change,
        output_dir=args.output_dir,
        evaluated_on_holdout=args.holdout,
        holdout_description=args.holdout_description,
    )
    print(verdict_markdown(verdict))


if __name__ == "__main__":
    main()
