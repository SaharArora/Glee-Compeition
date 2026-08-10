from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from glee_eval.data.schemas import EpisodeResult
from glee_eval.storage.trajectories import ensure_dir, write_jsonl


def _failure_types(episode: EpisodeResult) -> list[str]:
    if not episode.failure_diagnostics:
        return []
    return [failure.failure_type for failure in episode.failure_diagnostics]


def _terminal_brief(episode: EpisodeResult) -> str:
    terminal = episode.terminal_outcome
    family = episode.scenario.game_family
    if family == "bargaining":
        result = terminal.get("result")
        round_number = terminal.get("agreement_round")
        return f"{result} r={round_number}" if round_number else str(result)
    if family == "negotiation":
        result = terminal.get("result")
        price = terminal.get("normalized_price")
        return f"{result} p={price:.3f}" if isinstance(price, (int, float)) else str(result)
    if family == "persuasion":
        return f"sales={terminal.get('sales')} surplus={terminal.get('realized_surplus')}"
    return json.dumps(terminal, sort_keys=True)


def episode_to_match_row(episode: EpisodeResult, source: str) -> dict[str, Any]:
    failures = _failure_types(episode)
    return {
        "episode_id": episode.episode_id,
        "source": source,
        "scenario_id": episode.scenario.scenario_id,
        "family": episode.scenario.game_family,
        "candidate_role": episode.scenario.candidate_role,
        "opponent_role": episode.scenario.opponent_role,
        "opponent_archetype": episode.opponent_spec.archetype,
        "candidate_payoff": episode.candidate_payoff,
        "opponent_payoff": episode.opponent_payoff,
        "regret": episode.metrics.get("regret"),
        "trade_or_sale": episode.metrics.get("trade_or_sale"),
        "ir_violation": episode.metrics.get("ir_violation"),
        "illegal_action": episode.metrics.get("illegal_action"),
        "malformed_response": episode.metrics.get("malformed_response"),
        "failure_types": ",".join(failures),
        "terminal_brief": _terminal_brief(episode),
        "seed": episode.scenario.seed,
    }


def build_match_rows(
    tournament_episodes: list[EpisodeResult],
    elite_episodes: list[EpisodeResult],
) -> list[dict[str, Any]]:
    rows = [episode_to_match_row(episode, "tournament") for episode in tournament_episodes]
    rows.extend(episode_to_match_row(episode, "search_elite") for episode in elite_episodes)
    return rows


def write_match_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    ensure_dir(path.parent)
    fieldnames = [
        "episode_id",
        "source",
        "scenario_id",
        "family",
        "candidate_role",
        "opponent_role",
        "opponent_archetype",
        "candidate_payoff",
        "opponent_payoff",
        "regret",
        "trade_or_sale",
        "ir_violation",
        "illegal_action",
        "malformed_response",
        "failure_types",
        "terminal_brief",
        "seed",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return ""
    return str(value)


def match_report_markdown(rows: list[dict[str, Any]], *, max_rows: int = 200) -> str:
    by_family = defaultdict(list)
    by_archetype = defaultdict(list)
    failures = Counter()
    for row in rows:
        by_family[row["family"]].append(row)
        by_archetype[row["opponent_archetype"]].append(row)
        for failure in str(row.get("failure_types") or "").split(","):
            if failure:
                failures[failure] += 1

    lines = [
        "# Match Ledger",
        "",
        f"Total compiled matches: {len(rows)}",
        "",
        "## Family Summary",
        "",
        "| Family | Matches | Mean Payoff | Mean Regret | Trade/Sale Rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for family, family_rows in sorted(by_family.items()):
        payoffs = [float(row["candidate_payoff"]) for row in family_rows if row.get("candidate_payoff") is not None]
        regrets = [float(row["regret"]) for row in family_rows if row.get("regret") is not None]
        trades = [1.0 if row.get("trade_or_sale") in {True, "True", "true", 1, "1"} else 0.0 for row in family_rows]
        lines.append(
            f"| {family} | {len(family_rows)} | {_fmt(mean(payoffs) if payoffs else None)} | "
            f"{_fmt(mean(regrets) if regrets else None)} | {_fmt(mean(trades) if trades else None)} |"
        )

    lines.extend(["", "## Opponent Archetype Summary", "", "| Archetype | Matches | Mean Payoff | Mean Regret |", "|---|---:|---:|---:|"])
    for archetype, archetype_rows in sorted(by_archetype.items()):
        payoffs = [float(row["candidate_payoff"]) for row in archetype_rows if row.get("candidate_payoff") is not None]
        regrets = [float(row["regret"]) for row in archetype_rows if row.get("regret") is not None]
        lines.append(
            f"| {archetype} | {len(archetype_rows)} | {_fmt(mean(payoffs) if payoffs else None)} | "
            f"{_fmt(mean(regrets) if regrets else None)} |"
        )

    lines.extend(["", "## Failure Types", ""])
    if failures:
        for failure, count in failures.most_common():
            lines.append(f"- `{failure}`: {count}")
    else:
        lines.append("No discrete failure diagnostics fired.")

    ranked = sorted(rows, key=lambda row: float(row.get("regret") or 0.0), reverse=True)
    displayed = ranked[:max_rows]
    lines.extend(
        [
            "",
            f"## Highest-Regret Matches {'(truncated)' if len(rows) > max_rows else ''}",
            "",
            "| # | Episode | Source | Family | Role | Opponent | Payoff | Regret | Terminal | Failures |",
            "|---:|---|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for idx, row in enumerate(displayed, start=1):
        lines.append(
            f"| {idx} | `{row['episode_id']}` | {row['source']} | {row['family']} | {row['candidate_role']} | "
            f"{row['opponent_archetype']} | {_fmt(row['candidate_payoff'])} | {_fmt(row['regret'])} | "
            f"{row['terminal_brief']} | {row.get('failure_types') or ''} |"
        )
    if len(rows) > max_rows:
        lines.extend(["", f"Showing {max_rows} of {len(rows)} matches. See `match_ledger.csv` or `match_ledger.jsonl` for the full ledger."])
    lines.append("")
    return "\n".join(lines)


def write_match_ledger(
    run_dir: Path,
    tournament_episodes: list[EpisodeResult],
    elite_episodes: list[EpisodeResult],
    *,
    max_report_rows: int = 200,
) -> dict[str, str]:
    match_dir = ensure_dir(run_dir / "matches")
    rows = build_match_rows(tournament_episodes, elite_episodes)
    jsonl = write_jsonl(match_dir / "match_ledger.jsonl", rows)
    csv_path = write_match_csv(match_dir / "match_ledger.csv", rows)
    markdown = match_dir / "match_ledger.md"
    markdown.write_text(match_report_markdown(rows, max_rows=max_report_rows), encoding="utf-8")
    return {"jsonl": str(jsonl), "csv": str(csv_path), "markdown": str(markdown)}

