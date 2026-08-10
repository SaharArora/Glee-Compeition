from __future__ import annotations

import hashlib
import random
from typing import Any

from glee_eval.data.schemas import OpponentSpec, Scenario

ARCHETYPES = [
    "rational",
    "fairness_sensitive",
    "aggressive_extractor",
    "conceding",
    "boulware",
    "reciprocal",
    "random",
    "myopic",
    "level_0",
    "level_1",
    "level_2",
    "commitment_respecting",
    "commitment_testing",
    "deceptive",
    "adaptive",
    "historical_imitator",
]


DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "bargaining": {
        "money_to_divide": 100,
        "max_rounds": 6,
        "complete_information": True,
        "messages_allowed": False,
        "delta_1": 0.9,
        "delta_2": 0.95,
    },
    "negotiation": {
        "seller_value": 0.75,
        "buyer_value": 1.05,
        "product_price_order": 1_000_000,
        "max_rounds": 6,
        "complete_information": True,
        "messages_allowed": False,
    },
    "persuasion": {
        "p": 0.65,
        "v": 1.2,
        "c": 0.0,
        "product_price": 100,
        "total_rounds": 20,
        "is_seller_know_cv": True,
        "is_buyer_know_p": True,
        "seller_message_type": "binary",
        "is_myopic": False,
        "allow_buyer_message": False,
    },
}


def stable_id(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def sample_opponent_spec(game_family: str, rng: random.Random) -> OpponentSpec:
    archetype = rng.choice(ARCHETYPES)
    params: dict[str, Any] = {}
    if game_family == "bargaining":
        params = {
            "target_share": rng.uniform(0.48, 0.78),
            "concession_rate": rng.uniform(0.0, 0.08),
            "accept_threshold": rng.uniform(0.30, 0.55),
            "action_noise": rng.uniform(0.0, 0.03),
        }
    elif game_family == "negotiation":
        params = {
            "concession_rate": rng.uniform(0.0, 0.08),
            "accept_margin": rng.uniform(0.0, 0.08),
            "action_noise": rng.uniform(0.0, 0.03),
        }
    elif game_family == "persuasion":
        params = {
            "honesty": rng.uniform(0.2, 0.95),
            "trust_prior": rng.uniform(0.1, 0.9),
            "memory_length": rng.choice([1, 3, 5, 20]),
        }
    return OpponentSpec(archetype=archetype, game_family=game_family, parameters=params, seed=rng.randrange(10**9))


def sample_scenario(game_family: str, seed: int, candidate_role: str | None = None) -> Scenario:
    rng = random.Random(seed)
    config = dict(DEFAULT_CONFIGS[game_family])
    if game_family == "bargaining":
        config["delta_1"] = round(rng.uniform(0.75, 1.0), 2)
        config["delta_2"] = round(rng.uniform(0.75, 1.0), 2)
    elif game_family == "negotiation":
        config["seller_value"] = round(rng.uniform(0.5, 0.95), 2)
        config["buyer_value"] = round(rng.uniform(config["seller_value"], 1.25), 2)
    elif game_family == "persuasion":
        config["p"] = round(rng.uniform(0.2, 0.85), 2)
        config["v"] = round(rng.uniform(1.05, 1.5), 2)
    roles = {
        "bargaining": ("player_1", "player_2"),
        "negotiation": ("seller", "buyer"),
        "persuasion": ("seller", "buyer"),
    }[game_family]
    cand_role = candidate_role or rng.choice(roles)
    opp_role = roles[1] if cand_role == roles[0] else roles[0]
    opponent = sample_opponent_spec(game_family, rng)
    payload = f"{game_family}:{seed}:{cand_role}:{opponent.archetype}:{opponent.parameters}:{config}"
    return Scenario(
        scenario_id=stable_id(payload),
        game_family=game_family,
        config_id=stable_id(str(config)),
        public_parameters=config,
        candidate_role=cand_role,
        opponent_role=opp_role,
        opponent_spec={
            "archetype": opponent.archetype,
            "game_family": opponent.game_family,
            "parameters": opponent.parameters,
            "seed": opponent.seed,
            "version": opponent.version,
            "description": opponent.description,
        },
        seed=seed,
        source="synthetic",
    )

