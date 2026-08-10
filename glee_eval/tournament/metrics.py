from __future__ import annotations

from math import sqrt
from statistics import mean, median, pstdev
from typing import Any

from glee_eval.data.schemas import EpisodeResult


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def bootstrap_ci_mean(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    # Normal approximation keeps this deterministic and dependency-free.
    if len(values) == 1:
        return values[0], values[0]
    m = mean(values)
    se = pstdev(values) / sqrt(len(values))
    return m - 1.96 * se, m + 1.96 * se


def summarize(values: list[float]) -> dict[str, Any]:
    low, high = bootstrap_ci_mean(values)
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "std": pstdev(values) if len(values) > 1 else 0.0 if values else None,
        "p10": quantile(values, 0.10),
        "p25": quantile(values, 0.25),
        "p75": quantile(values, 0.75),
        "p90": quantile(values, 0.90),
        "mean_ci95_low": low,
        "mean_ci95_high": high,
    }


def summarize_episodes(episodes: list[EpisodeResult]) -> dict[str, Any]:
    payoffs = [episode.candidate_payoff for episode in episodes]
    trade = [1.0 if episode.terminal_outcome.get("result") in {"accept", "AcceptOffer", "completed"} and episode.metrics.get("trade_or_sale", False) else 0.0 for episode in episodes]
    malformed = [episode.metrics.get("malformed_response", 0.0) for episode in episodes]
    illegal = [episode.metrics.get("illegal_action", 0.0) for episode in episodes]
    ir = [episode.metrics.get("ir_violation", 0.0) for episode in episodes]
    by_family: dict[str, list[EpisodeResult]] = {}
    by_role: dict[str, list[EpisodeResult]] = {}
    by_archetype: dict[str, list[EpisodeResult]] = {}
    for episode in episodes:
        by_family.setdefault(episode.scenario.game_family, []).append(episode)
        by_role.setdefault(episode.scenario.candidate_role, []).append(episode)
        by_archetype.setdefault(episode.opponent_spec.archetype, []).append(episode)
    return {
        "episodes": len(episodes),
        "candidate_payoff": summarize(payoffs),
        "agreement_or_sale_rate": mean(trade) if trade else None,
        "malformed_response_rate": mean(malformed) if malformed else None,
        "illegal_action_rate": mean(illegal) if illegal else None,
        "individual_rationality_violation_rate": mean(ir) if ir else None,
        "by_family": {key: summarize([ep.candidate_payoff for ep in value]) for key, value in sorted(by_family.items())},
        "by_role": {key: summarize([ep.candidate_payoff for ep in value]) for key, value in sorted(by_role.items())},
        "by_opponent_archetype": {key: summarize([ep.candidate_payoff for ep in value]) for key, value in sorted(by_archetype.items())},
    }

