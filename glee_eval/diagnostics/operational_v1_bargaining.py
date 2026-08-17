"""Exact executable schema-v1 bargaining comparator for Model-A v2."""

from __future__ import annotations

import math
import random
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from glee_eval.data.schemas import GameState, OpponentSpec
from glee_eval.opponents.policies import BargainingPolicy
from glee_eval.population.opponent_fit import OpponentPopulation
from glee_eval.population.sampler import sample_opponent_spec


ACTION_CLASSES = ("offer", "accept", "reject", "walkaway")


class OperationalV1BargainingComparator:
    """Monte-Carlo integration by executing the pinned operational policy.

    Unlike the rejected approximation, each draw preserves archetype, complete
    sampled parameters, action-noise seed, and the policy's round/horizon logic.
    In particular, ``boulware`` and ``late_conceding`` early offers are frozen by
    the real :class:`BargainingPolicy` implementation.
    """

    def __init__(self, population_path: str | Path, *, draws: int = 4096, seed: int = 20260817):
        population = OpponentPopulation.load(population_path)
        if population is None or int(population.payload.get("schema_version", 0)) != 1:
            raise ValueError("operational comparator requires schema-v1 opponent population")
        self.population_path = str(Path(population_path).resolve())
        self.draws = int(draws)
        self.seed = int(seed)
        rng = random.Random(self.seed)
        self.specs: list[OpponentSpec] = [
            sample_opponent_spec("bargaining", rng, population=population)
            for _ in range(self.draws)
        ]
        if len(self.specs) != self.draws or not self.specs:
            raise ValueError("operational comparator produced no draws")
        if any(spec.parameters.get("parameter_source") != "fitted_real_population" for spec in self.specs):
            raise ValueError("operational comparator escaped the schema-v1 fitted population path")
        self.archetype_counts = dict(sorted(Counter(spec.archetype for spec in self.specs).items()))
        self._prediction_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    @staticmethod
    def _policy_history(row: dict[str, Any]) -> list[dict[str, Any]]:
        money = float(row["config"]["money_to_divide"])
        output: list[dict[str, Any]] = []
        for item in row["visible_history"]:
            if item["action_type"] == "offer":
                self_gain = round(money * float(item["offer_self_share"]), 2)
                output.append({
                    "role": item["role"],
                    "round": item["round"],
                    "action_type": "offer",
                    "numeric_action": self_gain,
                    "self_gain": self_gain,
                    "other_gain": round(money - self_gain, 2),
                })
            else:
                output.append({
                    "role": item["role"],
                    "round": item["round"],
                    "action_type": "decision",
                    "accept_reject": item["decision"],
                    "structured": {"decision": item["decision"]},
                })
        return output

    def state_for(self, row: dict[str, Any]) -> GameState:
        return GameState(
            scenario_id="operational-v1-comparator",
            game_id=str(row["game_id"]),
            game_family="bargaining",
            role=str(row["role"]),
            round=int(row["round"]),
            horizon=int(row["max_rounds"]),
            public_parameters=dict(row["config"]),
            private_parameters={},
            visible_transcript=self._policy_history(row),
            valid_action_schema={"kind": row["v1_context"]["valid_kind"]},
        )

    @staticmethod
    def classify(action: Any) -> str:
        if action.action_type == "offer":
            return "offer"
        decision = str(action.accept_reject or action.structured.get("decision") or "").lower()
        if decision in {"accept", "accepted", "acceptoffer"}:
            return "accept"
        if decision in {"reject", "rejected", "rejectoffer"}:
            return "reject"
        if decision in {"walkaway", "exit", "quit", "nodeal"}:
            return "walkaway"
        raise ValueError(f"operational policy returned unknown bargaining action {decision!r}")

    def predict(self, row: dict[str, Any]) -> dict[str, Any]:
        state = self.state_for(row)
        cache_key = (
            state.valid_action_schema["kind"], state.round, state.horizon,
            round(float(state.public_parameters["money_to_divide"]), 9),
            row["v1_context"].get("offered_share"), bool(row.get("offer_share") is not None),
        )
        if cache_key in self._prediction_cache:
            return self._prediction_cache[cache_key]
        counts: Counter[str] = Counter()
        stops = 0
        offers: list[float] = []
        money = float(row["config"]["money_to_divide"])
        for spec in self.specs:
            action = BargainingPolicy(spec).decide(state)
            label = self.classify(action)
            counts[label] += 1
            if label in {"accept", "walkaway"} or (
                label == "reject" and int(row["round"]) >= int(row["max_rounds"])
            ):
                stops += 1
            if label == "offer":
                if action.numeric_action is None:
                    raise ValueError("operational policy offer lacks numeric action")
                share = float(action.numeric_action) / money
                if not math.isfinite(share) or not 0.0 <= share <= 1.0:
                    raise ValueError("operational policy offer escaped normalized support")
                offers.append(share)
        result = {
            "action": {label: counts[label] / self.draws for label in ACTION_CLASSES},
            "stop": stops / self.draws,
            "offer_samples": offers if row.get("offer_share") is not None else None,
            "draws": self.draws,
            "archetype_counts": self.archetype_counts,
            "mean_offer": mean(offers) if offers else None,
        }
        self._prediction_cache[cache_key] = result
        return result
