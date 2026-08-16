"""Deterministic fit/holdout partitions of the real dataset.

Every number produced in this repo so far came from fitting and evaluating on the
same real data, so a result could be restating what it was fitted on and nobody
would see the difference. These splits give an evaluation something the fit never
saw.

Two axes, because they answer different questions:

* `model` -- partition by the LLM behind each player. The fit slice never observes
  the held-out families at all, so evaluating against opponents fitted from the
  holdout answers "does this generalize to an opponent type we did not tune
  against?". The released data has 13 LLM families of roughly 12k games each plus
  two otree sources, so a 25% holdout leaves several intact families on each side.
* `config` -- partition by configuration. Answers "does this generalize to a
  configuration regime we did not fit on?".

Assignment is by hash of a stable key, never by RNG, so the same game lands in the
same partition on every machine and every rerun, and no split state has to be
stored alongside the artifacts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from glee_eval.population.config_keys import canonical_config_key

FIT = "fit"
HOLDOUT = "holdout"
SPLIT_MODES = ("none", "model", "config", "config_signature")
DEFAULT_HOLDOUT_FRACTION = 0.25

_BUCKETS = 1000


def _bucket(value: str) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % _BUCKETS


def is_holdout_key(value: str, holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION) -> bool:
    return _bucket(value) < int(round(holdout_fraction * _BUCKETS))


def _models(record: dict[str, Any]) -> list[str]:
    return [str(record.get(field) or "") for field in ("player_1_model", "player_2_model") if record.get(field)]


def _config_key(record: dict[str, Any]) -> str:
    config_id = record.get("config_id")
    if config_id:
        return str(config_id)
    configuration = record.get("configuration")
    if isinstance(configuration, str):
        return configuration
    if isinstance(configuration, dict):
        return json.dumps(configuration.get("game_args") or configuration, sort_keys=True)
    return str(record.get("game_id") or "")


def _normalized_config_signature(record: dict[str, Any]) -> str:
    configuration = record.get("configuration") or record.get("public_parameters") or {}
    if isinstance(configuration, str):
        try:
            configuration = json.loads(configuration)
        except (TypeError, ValueError):
            return configuration
    if isinstance(configuration, dict):
        configuration = configuration.get("game_args") or configuration
        return canonical_config_key(str(record.get("game_family") or ""), configuration)
    return str(configuration)


def partition_of(
    record: dict[str, Any],
    mode: str = "none",
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> str:
    """Which partition a game or event belongs to.

    Under `model`, a record is held out when *either* player's model is a held-out
    family. Requiring both would leak the held-out family's behavior into the fit
    slice through its games against fit-slice opponents.
    """

    if mode == "none":
        return FIT
    if mode == "model":
        models = _models(record)
        if not models:
            return FIT
        return HOLDOUT if any(is_holdout_key(model, holdout_fraction) for model in models) else FIT
    if mode == "config":
        return HOLDOUT if is_holdout_key(_config_key(record), holdout_fraction) else FIT
    if mode == "config_signature":
        return HOLDOUT if is_holdout_key(_normalized_config_signature(record), holdout_fraction) else FIT
    raise ValueError(f"Unsupported split mode: {mode}. Use one of {SPLIT_MODES}.")


def keeps(
    record: dict[str, Any],
    *,
    mode: str = "none",
    split: str | None = None,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> bool:
    """True when `record` belongs in the requested split."""

    if split is None or mode == "none":
        return True
    return partition_of(record, mode, holdout_fraction) == split


def split_provenance(mode: str, split: str | None, holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION) -> dict[str, Any]:
    """Recorded on every fitted artifact so a run cannot misreport what it saw."""

    return {
        "split_mode": mode,
        "split": split or "all",
        "holdout_fraction": holdout_fraction if mode != "none" else 0.0,
        "note": (
            "Assignment is by SHA1 bucket of a stable key, so partitions are reproducible "
            "without storing split state."
        ),
    }


def add_split_arguments(parser: Any) -> None:
    parser.add_argument("--split-mode", default="none", choices=list(SPLIT_MODES))
    parser.add_argument("--split", default=None, choices=[FIT, HOLDOUT])
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
