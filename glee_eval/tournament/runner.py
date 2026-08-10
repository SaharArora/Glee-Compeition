from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any

from glee_eval.adapters.candidate_agent import CandidateAgent, load_agent
from glee_eval.data.ingest import terminal_bargaining, terminal_negotiation, terminal_persuasion
from glee_eval.data.schemas import DecisionRecord, EpisodeResult, GameState, OpponentSpec, Scenario, to_jsonable
from glee_eval.diagnostics.failures import diagnose_episode
from glee_eval.opponents.policies import PolicyFactory
from glee_eval.population.sampler import sample_scenario
from glee_eval.storage.trajectories import write_json, write_jsonl
from glee_eval.tournament.metrics import summarize_episodes


def _schema(kind: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, **extra}


def _state(
    scenario: Scenario,
    game_id: str,
    role: str,
    round_number: int,
    horizon: int,
    transcript: list[dict[str, Any]],
    kind: str,
    private: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> GameState:
    visible_transcript = _visible_transcript(scenario.game_family, role, round_number, transcript)
    return GameState(
        scenario_id=scenario.scenario_id,
        game_id=game_id,
        game_family=scenario.game_family,
        role=role,
        round=round_number,
        horizon=horizon,
        public_parameters=dict(scenario.public_parameters),
        private_parameters=private or {},
        visible_transcript=visible_transcript,
        valid_action_schema=_schema(kind, seller_message_type=scenario.public_parameters.get("seller_message_type")),
        metadata=metadata or {},
    )


def _visible_transcript(
    game_family: str,
    role: str,
    round_number: int,
    transcript: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if game_family != "persuasion":
        return list(transcript)
    visible: list[dict[str, Any]] = []
    for item in transcript:
        if role == "buyer" and item.get("action_type") == "nature_quality" and item.get("round") == round_number:
            continue
        visible.append(dict(item))
    return visible


def _decision_record(
    scenario: Scenario,
    game_id: str,
    state: GameState,
    action: Any,
    terminal: dict[str, Any] | None = None,
    player_payoff: float | None = None,
    opponent_payoff: float | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"{game_id}:{len(state.visible_transcript)}:{state.role}",
        game_id=game_id,
        scenario_id=scenario.scenario_id,
        source=scenario.source,
        game_family=scenario.game_family,
        config_id=scenario.config_id,
        role=state.role,
        round=state.round,
        visible_state=to_jsonable(state),
        action=to_jsonable(action),
        terminal_result=terminal,
        player_payoff=player_payoff,
        opponent_payoff=opponent_payoff,
        checks={"legal": getattr(action, "is_legal", True), "parseable": getattr(action, "is_parseable", True)},
    )


def _policy_for_role(scenario: Scenario, candidate: CandidateAgent, role: str):
    if role == scenario.candidate_role:
        return candidate
    return PolicyFactory.create(scenario.game_family, scenario.opponent_spec)


def run_episode(scenario: Scenario, candidate: CandidateAgent) -> EpisodeResult:
    if scenario.game_family == "bargaining":
        return _run_bargaining(scenario, candidate)
    if scenario.game_family == "negotiation":
        return _run_negotiation(scenario, candidate)
    if scenario.game_family == "persuasion":
        return _run_persuasion(scenario, candidate)
    raise ValueError(f"Unsupported family: {scenario.game_family}")


def _run_bargaining(scenario: Scenario, candidate: CandidateAgent) -> EpisodeResult:
    cfg = scenario.public_parameters
    game_id = f"synthetic-{scenario.scenario_id}"
    horizon = int(cfg.get("max_rounds", 6))
    transcript: list[dict[str, Any]] = []
    records: list[DecisionRecord] = []
    rows: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    roles = ("player_1", "player_2")
    for round_number in range(1, horizon + 1):
        proposer = roles[0] if round_number % 2 else roles[1]
        receiver = roles[1] if proposer == roles[0] else roles[0]
        state = _state(scenario, game_id, proposer, round_number, horizon, transcript, "offer")
        offer = _policy_for_role(scenario, candidate, proposer).decide(state)
        money = float(cfg.get("money_to_divide", 100))
        self_gain = float(offer.structured.get("self_gain", offer.numeric_action or money / 2))
        other_gain = float(offer.structured.get("other_gain", money - self_gain))
        raw = {"player": "Alice" if proposer == "player_1" else "Bob", "round": round_number}
        if proposer == "player_1":
            raw.update({"alice_gain": self_gain, "bob_gain": other_gain})
        else:
            raw.update({"alice_gain": other_gain, "bob_gain": self_gain})
        rows.append(raw)
        event = {"round": round_number, "role": proposer, "action_type": "offer", "numeric_action": self_gain, "self_gain": self_gain, "other_gain": other_gain, "structured": offer.structured}
        transcript.append(event)
        records.append(_decision_record(scenario, game_id, state, offer))
        state = _state(scenario, game_id, receiver, round_number, horizon, transcript, "decision")
        decision = _policy_for_role(scenario, candidate, receiver).decide(state)
        rows.append({"player": "Alice" if receiver == "player_1" else "Bob", "round": round_number, "decision": decision.accept_reject})
        transcript.append({"round": round_number, "role": receiver, "action_type": "decision", "accept_reject": decision.accept_reject, "structured": decision.structured})
        records.append(_decision_record(scenario, game_id, state, decision))
        if decision.accept_reject == "accept":
            terminal = terminal_bargaining(rows, _config("bargaining", cfg))
            break
    if terminal is None:
        terminal = terminal_bargaining(rows, _config("bargaining", cfg))
    return _episode(scenario, candidate, game_id, transcript, records, terminal, roles)


def _run_negotiation(scenario: Scenario, candidate: CandidateAgent) -> EpisodeResult:
    cfg = scenario.public_parameters
    game_id = f"synthetic-{scenario.scenario_id}"
    horizon = int(cfg.get("max_rounds", 6))
    transcript: list[dict[str, Any]] = []
    records: list[DecisionRecord] = []
    rows: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    roles = ("seller", "buyer")
    names = {"seller": "Alice", "buyer": "Bob"}
    private = {"seller": {"seller_value": cfg.get("seller_value")}, "buyer": {"buyer_value": cfg.get("buyer_value")}}
    for round_number in range(1, horizon + 1):
        proposer = roles[0] if round_number % 2 else roles[1]
        receiver = roles[1] if proposer == roles[0] else roles[0]
        state = _state(scenario, game_id, proposer, round_number, horizon, transcript, "offer", private=private[proposer])
        offer = _policy_for_role(scenario, candidate, proposer).decide(state)
        rows.append({"player": names[proposer], "round": round_number, "product_price": offer.numeric_action})
        transcript.append({"round": round_number, "role": proposer, "action_type": "offer", "numeric_action": offer.numeric_action, "structured": offer.structured})
        records.append(_decision_record(scenario, game_id, state, offer))
        state = _state(scenario, game_id, receiver, round_number, horizon, transcript, "decision", private=private[receiver])
        decision = _policy_for_role(scenario, candidate, receiver).decide(state)
        rows.append({"player": names[receiver], "round": round_number, "decision": decision.accept_reject})
        transcript.append({"round": round_number, "role": receiver, "action_type": "decision", "accept_reject": decision.accept_reject, "structured": decision.structured})
        records.append(_decision_record(scenario, game_id, state, decision))
        if decision.accept_reject != "RejectOffer":
            terminal = terminal_negotiation(rows, _config("negotiation", cfg))
            break
    if terminal is None:
        terminal = terminal_negotiation(rows, _config("negotiation", cfg))
    return _episode(scenario, candidate, game_id, transcript, records, terminal, roles)


def _run_persuasion(scenario: Scenario, candidate: CandidateAgent) -> EpisodeResult:
    cfg = scenario.public_parameters
    game_id = f"synthetic-{scenario.scenario_id}"
    horizon = int(cfg.get("total_rounds", 20))
    rng = random.Random(scenario.seed)
    transcript: list[dict[str, Any]] = []
    records: list[DecisionRecord] = []
    rows: list[dict[str, Any]] = []
    roles = ("seller", "buyer")
    for round_number in range(1, horizon + 1):
        is_high = rng.random() < float(cfg.get("p", 0.65))
        worth = float(cfg.get("v", 1.2) if is_high else cfg.get("c", 0.0)) * float(cfg.get("product_price", 100))
        quality = "high-quality" if is_high else "low-quality"
        rows.append({"player": "Nature", "round": round_number, "round_quality": quality, "product_worth": worth})
        transcript.append({"round": round_number, "role": "nature", "action_type": "nature_quality", "quality": quality, "product_worth": worth})
        state = _state(scenario, game_id, "seller", round_number, horizon, transcript, "recommendation", private={"p": cfg.get("p")}, metadata={"quality": quality})
        seller_action = _policy_for_role(scenario, candidate, "seller").decide(state)
        seller_row = {"player": "Alice", "round": round_number}
        seller_row.update(seller_action.structured)
        rows.append(seller_row)
        transcript.append({"round": round_number, "role": "seller", "action_type": seller_action.action_type, "buy_no_buy": seller_action.buy_no_buy, "structured": seller_action.structured})
        records.append(_decision_record(scenario, game_id, state, seller_action))
        state = _state(scenario, game_id, "buyer", round_number, horizon, transcript, "buy_decision", private={"c": cfg.get("c"), "v": cfg.get("v")})
        buyer_action = _policy_for_role(scenario, candidate, "buyer").decide(state)
        rows.append({"player": "Bob", "round": round_number, "decision": buyer_action.buy_no_buy})
        transcript.append({"round": round_number, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": buyer_action.buy_no_buy, "structured": buyer_action.structured})
        records.append(_decision_record(scenario, game_id, state, buyer_action))
    terminal = terminal_persuasion(rows, _config("persuasion", cfg))
    return _episode(scenario, candidate, game_id, transcript, records, terminal, roles)


def _config(family: str, game_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_type": family,
        "player_1_args": {"public_name": "Alice"},
        "player_2_args": {"public_name": "Bob"},
        "game_args": dict(game_args),
    }


def _episode(
    scenario: Scenario,
    candidate: CandidateAgent,
    game_id: str,
    transcript: list[dict[str, Any]],
    records: list[DecisionRecord],
    terminal: dict[str, Any],
    roles: tuple[str, str],
) -> EpisodeResult:
    candidate_is_first = scenario.candidate_role == roles[0]
    candidate_payoff = float(terminal.get("player_1_payoff" if candidate_is_first else "player_2_payoff", 0.0) or 0.0)
    opponent_payoff = float(terminal.get("player_2_payoff" if candidate_is_first else "player_1_payoff", 0.0) or 0.0)
    reference_payoff = max(candidate_payoff, opponent_payoff, 0.5 if scenario.game_family != "persuasion" else candidate_payoff)
    metrics = {
        "trade_or_sale": terminal.get("result") in {"accept", "AcceptOffer"} or terminal.get("sales", 0) > 0,
        "malformed_response": 0.0,
        "illegal_action": 0.0,
        "ir_violation": 1.0 if candidate_payoff < -1e-9 else 0.0,
        "reference_payoff": reference_payoff,
        "regret": max(0.0, reference_payoff - candidate_payoff),
        "critical_round": transcript[-1].get("round") if transcript else None,
    }
    spec = OpponentSpec(
        archetype=scenario.opponent_spec.get("archetype", "unknown"),
        game_family=scenario.game_family,
        parameters=scenario.opponent_spec.get("parameters", {}),
        seed=int(scenario.opponent_spec.get("seed", 0)),
        version=scenario.opponent_spec.get("version", "0.1"),
        description=scenario.opponent_spec.get("description", ""),
    )
    episode = EpisodeResult(
        episode_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scenario.scenario_id}:{candidate.agent_id}")),
        scenario=scenario,
        candidate_agent_id=candidate.agent_id,
        opponent_spec=spec,
        full_transcript=transcript,
        decision_records=records,
        terminal_outcome=terminal,
        candidate_payoff=candidate_payoff,
        opponent_payoff=opponent_payoff,
        metrics=metrics,
        replay_artifacts={"scenario": to_jsonable(scenario)},
    )
    diagnostics = diagnose_episode(episode)
    return EpisodeResult(**{**to_jsonable(episode), "scenario": scenario, "opponent_spec": spec, "decision_records": records, "failure_diagnostics": diagnostics})


def run_tournament(
    agent_spec: str = "heuristic",
    families: list[str] | None = None,
    games: int = 100,
    seed: int = 42,
    output_dir: str | Path = "reports/tournament",
) -> dict[str, Any]:
    families = families or ["bargaining", "negotiation", "persuasion"]
    rng = random.Random(seed)
    agent = load_agent(agent_spec, seed=seed)
    episodes: list[EpisodeResult] = []
    for _ in range(games):
        family = rng.choice(families)
        scenario = sample_scenario(family, seed=rng.randrange(10**9))
        episodes.append(run_episode(scenario, agent))
    metrics = summarize_episodes(episodes)
    out = Path(output_dir)
    write_jsonl(out / "episodes.jsonl", [to_jsonable(ep) for ep in episodes])
    write_json(out / "metrics.json", metrics)
    return {"metrics": metrics, "episodes": episodes, "output_dir": str(out)}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run a synthetic GLEE-style tournament.")
    parser.add_argument("--agent", default="heuristic")
    parser.add_argument("--families", default="bargaining,negotiation,persuasion")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="reports/tournament")
    args = parser.parse_args(argv)
    result = run_tournament(
        agent_spec=args.agent,
        families=[part for part in args.families.split(",") if part],
        games=args.games,
        seed=args.seed,
        output_dir=args.output_dir,
    )
    print(json.dumps(result["metrics"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
