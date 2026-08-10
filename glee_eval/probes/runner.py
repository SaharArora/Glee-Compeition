from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.schemas import DecisionRecord, GameState, to_jsonable
from glee_eval.probes.extract import extract_from_processed
from glee_eval.storage.trajectories import write_json, write_jsonl


def _legality_check(state: GameState, action: Any) -> dict[str, Any]:
    kind = state.valid_action_schema.get("kind")
    legal = True
    errors: list[str] = []
    if kind == "offer" and action.numeric_action is None and "product_price" not in action.structured and "self_gain" not in action.structured:
        legal = False
        errors.append("missing numeric offer")
    if kind in {"decision", "buy_decision"}:
        decision = action.accept_reject or action.buy_no_buy or action.structured.get("decision")
        if not decision:
            legal = False
            errors.append("missing decision")
    return {"legal": legal, "errors": errors, "parseable": action.is_parseable}


def run_probes(
    agent_spec: str = "heuristic",
    family: str | None = None,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    limit: int | None = 1000,
    seed: int = 0,
    output_dir: str | Path = "reports/probes",
) -> dict[str, Any]:
    agent = load_agent(agent_spec, seed=seed)
    probes = extract_from_processed(data_dir=data_dir, family=family, limit=limit)
    records: list[DecisionRecord] = []
    for state in probes:
        action = agent.decide(state)
        historical = state.metadata.get("historical_action")
        checks = _legality_check(state, action)
        terminal = state.metadata.get("terminal_outcome")
        records.append(
            DecisionRecord(
                decision_id=f"probe:{state.game_id}:{state.round}:{state.role}:{len(records)}",
                game_id=state.game_id,
                scenario_id=state.scenario_id,
                source=state.metadata.get("source", "historical"),
                game_family=state.game_family,
                config_id=state.metadata.get("config_id", "unknown"),
                role=state.role,
                round=state.round,
                visible_state=to_jsonable(state),
                action=to_jsonable(action),
                historical_action=historical,
                terminal_result=terminal,
                player_payoff=(terminal or {}).get("player_1_payoff") if state.role in {"player_1", "seller"} else (terminal or {}).get("player_2_payoff"),
                opponent_payoff=(terminal or {}).get("player_2_payoff") if state.role in {"player_1", "seller"} else (terminal or {}).get("player_1_payoff"),
                estimated_regret=None,
                checks=checks,
                metadata={"note": "Historical continuation is not treated as a counterfactual."},
            )
        )
    legal_rate = sum(1 for record in records if record.checks.get("legal")) / len(records) if records else None
    summary = {
        "agent": agent.agent_id,
        "family": family or "all",
        "probes": len(records),
        "legal_action_rate": legal_rate,
        "format_failure_rate": sum(1 for record in records if not record.checks.get("parseable", True)) / len(records) if records else None,
    }
    out = Path(output_dir)
    write_jsonl(out / "decisions.jsonl", [to_jsonable(record) for record in records])
    write_json(out / "summary.json", summary)
    return {"summary": summary, "records": records}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run historical decision probes.")
    parser.add_argument("--agent", default="heuristic")
    parser.add_argument("--family")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir", default="reports/probes")
    args = parser.parse_args(argv)
    result = run_probes(args.agent, args.family, args.data_dir, args.limit, args.seed, args.output_dir)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

