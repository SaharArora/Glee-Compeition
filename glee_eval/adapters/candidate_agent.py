from __future__ import annotations

import json
import random
from importlib import import_module
from abc import ABC, abstractmethod
from typing import Any

from glee_eval.data.schemas import AgentAction, GameState, compact_id


class CandidateAgent(ABC):
    agent_id = "candidate"

    @abstractmethod
    def decide(self, state: GameState) -> AgentAction:
        raise NotImplementedError


class HistoricalActionAgent(CandidateAgent):
    agent_id = "historical"

    def decide(self, state: GameState) -> AgentAction:
        historical = state.metadata.get("historical_action") or {}
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, self.agent_id),
            actor_role=state.role,
            round=state.round,
            raw_text=json.dumps(historical, sort_keys=True),
            action_type=historical.get("action_type", "unknown"),
            numeric_action=historical.get("numeric_action"),
            message=historical.get("free_text_message"),
            accept_reject=historical.get("accept_reject"),
            buy_no_buy=historical.get("buy_no_buy"),
            structured=historical,
        )


class RandomLegalAgent(CandidateAgent):
    agent_id = "random_legal"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def decide(self, state: GameState) -> AgentAction:
        family = state.game_family
        schema = state.valid_action_schema
        structured: dict[str, Any] = {}
        action_type = "unknown"
        numeric = None
        accept_reject = None
        buy_no_buy = None
        message = None
        if family == "bargaining":
            if schema.get("kind") == "offer":
                money = float(state.public_parameters.get("money_to_divide", 100))
                share = self.rng.uniform(0.35, 0.75)
                numeric = round(money * share, 2)
                action_type = "offer"
                structured = {"self_gain": numeric, "other_gain": round(money - numeric, 2)}
            else:
                accept_reject = self.rng.choice(["accept", "reject"])
                action_type = "decision"
                structured = {"decision": accept_reject}
        elif family == "negotiation":
            if schema.get("kind") == "offer":
                order = float(state.public_parameters.get("product_price_order", 1_000_000))
                numeric = round(order * self.rng.uniform(0.6, 1.1), 2)
                action_type = "offer"
                structured = {"product_price": numeric}
            else:
                accept_reject = self.rng.choice(["AcceptOffer", "RejectOffer"])
                action_type = "decision"
                structured = {"decision": accept_reject}
        elif family == "persuasion":
            if state.role == "seller":
                buy_no_buy = self.rng.choice(["yes", "no"])
                action_type = "recommendation"
                structured = {"decision": buy_no_buy}
            else:
                buy_no_buy = self.rng.choice(["yes", "no"])
                action_type = "buy_decision"
                structured = {"decision": buy_no_buy}
        raw = json.dumps(structured, sort_keys=True)
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, self.agent_id, self.rng.random()),
            actor_role=state.role,
            round=state.round,
            raw_text=raw,
            action_type=action_type,
            numeric_action=numeric,
            message=message,
            accept_reject=accept_reject,
            buy_no_buy=buy_no_buy,
            structured=structured,
        )


class HeuristicAgent(CandidateAgent):
    agent_id = "heuristic"

    def decide(self, state: GameState) -> AgentAction:
        from glee_eval.opponents.policies import PolicyFactory

        policy = PolicyFactory.create(
            state.game_family,
            {
                "archetype": "rational",
                "parameters": {},
                "seed": int(state.metadata.get("seed", 0)),
            },
        )
        return policy.decide(state)


def load_agent(spec: str, seed: int = 0) -> CandidateAgent:
    if spec in {"historical", "echo"}:
        return HistoricalActionAgent()
    if spec in {"random", "random_legal"}:
        return RandomLegalAgent(seed=seed)
    if spec in {"heuristic", "rational"}:
        return HeuristicAgent()
    if ":" in spec:
        module_name, attr_name = spec.split(":", 1)
        module = import_module(module_name)
        factory_or_class = getattr(module, attr_name)
        agent = factory_or_class(seed=seed) if callable(factory_or_class) else factory_or_class
        if not isinstance(agent, CandidateAgent):
            raise TypeError(f"{spec} did not produce a CandidateAgent instance.")
        return agent
    raise ValueError(
        f"Unsupported agent spec '{spec}'. Use historical, random, heuristic, "
        "or a dynamic path like my_agents.baseline:MyAgent."
    )
