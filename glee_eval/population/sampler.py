from __future__ import annotations

import hashlib
import os
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


# Hand-picked ranges, kept only as the fallback when no fitted population is
# available. Every one of them is now known to be wrong about the real
# population -- real bargaining opponents accept in 0.41-0.50 rather than
# 0.30-0.55, real negotiators concede roughly four times faster, real senders are
# far more honest (median 0.875) and real buyers far more trusting (median 0.795).
# A run using these is measuring the agent against invented opponents.
UNCALIBRATED_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "bargaining": {
        "target_share": (0.48, 0.78),
        "concession_rate": (0.0, 0.08),
        "accept_threshold": (0.30, 0.55),
    },
    "negotiation": {
        "concession_rate": (0.0, 0.08),
        "accept_margin": (0.0, 0.08),
    },
    "persuasion": {
        "honesty": (0.2, 0.95),
        "trust_prior": (0.1, 0.9),
    },
}


def load_config_catalogue(path: str | None = None):
    """Real configuration catalogue, from a path or GLEE_CONFIG_CATALOGUE."""

    from glee_eval.population.config_catalogue import ConfigCatalogue

    return ConfigCatalogue.load(path or os.getenv("GLEE_CONFIG_CATALOGUE"))


def load_opponent_population(path: str | None = None):
    """Fitted opponent population, from an explicit path or GLEE_OPPONENT_POPULATION."""

    from glee_eval.population.opponent_fit import OpponentPopulation

    return OpponentPopulation.load(path or os.getenv("GLEE_OPPONENT_POPULATION"))


def sample_opponent_spec(
    game_family: str,
    rng: random.Random,
    population: Any = None,
    opponent_role: str | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> OpponentSpec:
    """Draw an opponent, from fitted real behavior when a population is available.

    The archetype selects a quantile window of observed behavior, so the label
    actually determines the parameters. Previously every parameter was drawn from a
    hand-picked range regardless of archetype, which both invented the opponents
    and left `policies.py`'s archetype defaults as dead code.
    """

    population = population if population is not None else load_opponent_population()
    params: dict[str, Any] = {}
    calibrated = False
    archetype: str
    bundle = None
    if population is not None and opponent_role is not None and scenario_config is not None:
        bundle = population.sample_bundle(game_family, opponent_role, scenario_config, rng)
    if bundle is not None:
        archetype = str(bundle["derived_archetype"])
        params = dict(bundle.get("parameters") or {})
        params["joint_bundle_id"] = str(bundle["bundle_id"])
        params["joint_bundle_role"] = str(bundle["role"])
        params["joint_draw_fallback_level"] = str(bundle["draw_fallback_level"])
        params["joint_latent_percentile"] = float(bundle.get("latent_percentile", 0.5))
        params["population_schema_version"] = int(population.payload.get("schema_version", 0))
        params["population_provenance"] = dict(population.payload.get("provenance") or {})
        calibrated = True
    else:
        archetype = rng.choice(ARCHETYPES)
    if population is not None and not calibrated:
        params = population.parameters(game_family, archetype, rng, role=opponent_role)
        calibrated = bool(params)
    if not calibrated:
        params = {name: rng.uniform(*bounds) for name, bounds in UNCALIBRATED_RANGES.get(game_family, {}).items()}
    if game_family == "persuasion":
        params.setdefault("memory_length", rng.choice([1, 3, 5, 20]))
        params["memory_length_source"] = "compatibility_metadata_policy_inert"
    else:
        if params.get("joint_bundle_id"):
            params.setdefault("action_noise", 0.0)
            params.setdefault("action_noise_source", "explicit_zero_when_bundle_residual_unidentified")
        else:
            params.setdefault("action_noise", rng.uniform(0.0, 0.03))
    if calibrated and "joint_bundle_id" in params:
        params["parameter_source"] = "fitted_joint_population"
    else:
        params["parameter_source"] = "fitted_real_population" if calibrated else "uncalibrated_hand_picked"
    return OpponentSpec(archetype=archetype, game_family=game_family, parameters=params, seed=rng.randrange(10**9))


def sample_scenario(
    game_family: str,
    seed: int,
    candidate_role: str | None = None,
    population: Any = None,
    catalogue: Any = None,
) -> Scenario:
    """Sample a scenario, using a real observed configuration when one is available.

    Falls back to the invented `DEFAULT_CONFIGS` perturbations only when no
    catalogue is present, and records which happened in the scenario metadata so a
    run cannot silently claim realistic configurations it did not use.
    """

    rng = random.Random(seed)
    population = population if population is not None else load_opponent_population()
    catalogue = catalogue if catalogue is not None else load_config_catalogue()
    sampled = catalogue.sample(game_family, rng) if catalogue is not None else None
    if sampled:
        config = sampled
        config_source = "observed_real_config"
    else:
        config_source = "invented_default_config"
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
    opponent = sample_opponent_spec(
        game_family,
        rng,
        population=population,
        opponent_role=opp_role,
        scenario_config=config,
    )
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
        metadata={
            "config_source": config_source,
            "parameter_source": opponent.parameters.get("parameter_source"),
            "joint_bundle_id": opponent.parameters.get("joint_bundle_id"),
            "joint_draw_fallback_level": opponent.parameters.get("joint_draw_fallback_level"),
            "joint_latent_type": opponent.archetype if opponent.parameters.get("joint_bundle_id") else None,
            "joint_latent_percentile": opponent.parameters.get("joint_latent_percentile"),
            "population_schema_version": opponent.parameters.get("population_schema_version"),
            "population_provenance": opponent.parameters.get("population_provenance"),
        },
    )
