from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from glee_eval.data.schemas import EpisodeResult, to_jsonable


def _episode_failure_types(episode: EpisodeResult) -> list[str]:
    failures = episode.failure_diagnostics or []
    if not failures:
        return ["NONE"]
    return [failure.failure_type for failure in failures]


def _cluster_key(episode: EpisodeResult, failure_type: str) -> tuple[str, str, str, str]:
    return (
        episode.scenario.game_family,
        episode.scenario.candidate_role,
        episode.opponent_spec.archetype,
        failure_type,
    )


def generate_hypotheses(episodes: list[EpisodeResult], elite_episodes: list[EpisodeResult] | None = None) -> dict[str, Any]:
    elite_episodes = elite_episodes or []
    cluster_rows: dict[tuple[str, str, str, str], list[EpisodeResult]] = defaultdict(list)
    for episode in episodes + elite_episodes:
        for failure_type in _episode_failure_types(episode):
            cluster_rows[_cluster_key(episode, failure_type)].append(episode)

    clusters = []
    for (family, role, archetype, failure_type), rows in cluster_rows.items():
        payoffs = [row.candidate_payoff for row in rows]
        regrets = [float(row.metrics.get("regret", 0.0)) for row in rows]
        clusters.append(
            {
                "family": family,
                "candidate_role": role,
                "opponent_archetype": archetype,
                "failure_type": failure_type,
                "count": len(rows),
                "mean_payoff": mean(payoffs) if payoffs else None,
                "mean_regret": mean(regrets) if regrets else None,
                "max_regret": max(regrets) if regrets else None,
                "example_episode_id": rows[0].episode_id,
            }
        )
    clusters.sort(key=lambda row: (row["mean_regret"] or 0.0, -(row["mean_payoff"] or 0.0), row["count"]), reverse=True)

    hypotheses = []
    for cluster in clusters[:20]:
        if cluster["failure_type"] == "NONE" and (cluster["mean_regret"] or 0.0) < 0.1:
            continue
        hypotheses.append(
            {
                "hypothesis": (
                    f"{cluster['family']} as {cluster['candidate_role']} against "
                    f"{cluster['opponent_archetype']} may be weak around {cluster['failure_type']}."
                ),
                "evidence": {
                    "count": cluster["count"],
                    "mean_payoff": cluster["mean_payoff"],
                    "mean_regret": cluster["mean_regret"],
                    "max_regret": cluster["max_regret"],
                    "example_episode_id": cluster["example_episode_id"],
                },
                "next_check": "Inspect the example transcript and compare the critical decision with the reference/regret signal.",
            }
        )

    worst = sorted(episodes + elite_episodes, key=lambda ep: float(ep.metrics.get("regret", 0.0)), reverse=True)[:20]
    return {
        "hypotheses": hypotheses,
        "clusters": clusters[:100],
        "worst_episodes": [
            {
                "episode_id": episode.episode_id,
                "family": episode.scenario.game_family,
                "role": episode.scenario.candidate_role,
                "opponent_archetype": episode.opponent_spec.archetype,
                "candidate_payoff": episode.candidate_payoff,
                "regret": episode.metrics.get("regret"),
                "scenario": to_jsonable(episode.scenario),
            }
            for episode in worst
        ],
    }


def hypotheses_markdown(report: dict[str, Any]) -> str:
    lines = ["# Experiment Hypotheses", ""]
    hypotheses = report.get("hypotheses", [])
    if not hypotheses:
        lines.append("No high-regret hypothesis clusters were found in this run.")
    for idx, item in enumerate(hypotheses, start=1):
        evidence = item.get("evidence", {})
        lines.extend(
            [
                f"## {idx}. {item['hypothesis']}",
                "",
                f"- Count: {evidence.get('count')}",
                f"- Mean payoff: {evidence.get('mean_payoff')}",
                f"- Mean regret: {evidence.get('mean_regret')}",
                f"- Max regret: {evidence.get('max_regret')}",
                f"- Example episode: `{evidence.get('example_episode_id')}`",
                f"- Next check: {item.get('next_check')}",
                "",
            ]
        )
    lines.extend(["## Worst Episodes", ""])
    for episode in report.get("worst_episodes", [])[:20]:
        lines.append(
            f"- `{episode['episode_id']}`: {episode['family']} as {episode['role']} "
            f"vs {episode['opponent_archetype']}, payoff={episode['candidate_payoff']}, regret={episode['regret']}"
        )
    lines.append("")
    return "\n".join(lines)

