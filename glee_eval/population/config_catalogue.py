"""The catalogue of game configurations actually present in the released data.

`sample_scenario` invented configurations from independent `rng.uniform` draws.
That was wrong in four separate ways, all of which distorted measurement:

* `max_rounds` was 6, while real bargaining uses 12 or 99 and real negotiation 10
  or 30. Because `max_rounds` is part of both the exact and coarse support-index
  bucket keys, *every* bargaining and negotiation coverage lookup missed and fell
  back to the config-agnostic level -- 0 of 1882 lookups reached `exact`.
* `complete_information` was always True, while about 49% of real bargaining and
  negotiation games hide the counterpart's value.
* `buyer_value` was drawn as `uniform(seller_value, 1.25)`, so a no-trade zone
  never occurred -- against 61% of real negotiation configs having one.
* Values were drawn continuously, while the real parameters sit on a small
  discrete grid, so no sampled config ever matched a real one exactly.

Sampling whole observed configurations rather than per-parameter marginals also
preserves the joint structure, which matters: whether there are gains from trade
is a property of the `seller_value`/`buyer_value` pair, not of either alone.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json


FAMILIES = ("bargaining", "negotiation", "persuasion")

# Parameters that define a playable configuration, per family. Anything else on a
# real config (identifiers, bookkeeping) is dropped so the catalogue stays a set
# of game settings rather than a set of games.
CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "bargaining": ("money_to_divide", "max_rounds", "complete_information", "messages_allowed", "delta_1", "delta_2"),
    "negotiation": (
        "seller_value",
        "buyer_value",
        "product_price_order",
        "max_rounds",
        "complete_information",
        "messages_allowed",
    ),
    "persuasion": (
        "p",
        "v",
        "c",
        "product_price",
        "total_rounds",
        "is_seller_know_cv",
        "is_buyer_know_p",
        "seller_message_type",
        "is_myopic",
        "allow_buyer_message",
    ),
}


# Optional fields that real configs frequently omit, with the defaults taken from
# the upstream constructor signatures rather than guessed. 13,021 of 13,506 real
# persuasion configs omit is_buyer_know_p and allow_buyer_message; skipping those
# configs would have discarded almost the whole family.
#   games/persuasion/persuasion.py: is_seller_know_cv=True, is_buyer_know_p=True,
#   seller_message_type="text", allow_buyer_message=False, total_rounds=20, v=0
CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "bargaining": {"messages_allowed": False, "complete_information": True},
    "negotiation": {"messages_allowed": False, "complete_information": True},
    "persuasion": {
        "is_seller_know_cv": True,
        "is_buyer_know_p": True,
        "seller_message_type": "text",
        "allow_buyer_message": False,
        "is_myopic": False,
        "total_rounds": 20,
        "v": 0,
    },
}


def _game_args(game: dict[str, Any]) -> dict[str, Any]:
    configuration = game.get("configuration")
    if isinstance(configuration, str):
        try:
            configuration = json.loads(configuration)
        except json.JSONDecodeError:
            configuration = {}
    if not isinstance(configuration, dict):
        return {}
    args = configuration.get("game_args")
    return args if isinstance(args, dict) else {}


def build_config_catalogue(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "models/config_catalogue",
) -> dict[str, Any]:
    games_path = Path(data_dir) / "processed" / "games.jsonl"
    if not games_path.exists():
        raise FileNotFoundError(f"Missing processed games file: {games_path}")

    counters: dict[str, Counter] = {family: Counter() for family in FAMILIES}
    scanned = 0
    skipped = 0
    for game in iter_jsonl(games_path):
        scanned += 1
        family = str(game.get("game_family") or "")
        if family not in counters:
            skipped += 1
            continue
        args = _game_args(game)
        if not args:
            skipped += 1
            continue
        defaults = CONFIG_DEFAULTS.get(family, {})
        resolved = {}
        for field in CONFIG_FIELDS[family]:
            value = args.get(field)
            if value is None:
                value = defaults.get(field)
            resolved[field] = value
        if any(value is None for value in resolved.values()):
            skipped += 1
            continue
        counters[family][json.dumps(resolved, sort_keys=True)] += 1

    families: dict[str, Any] = {}
    for family, counter in counters.items():
        entries = [{"config": json.loads(payload), "count": count} for payload, count in counter.most_common()]
        families[family] = {
            "distinct_configs": len(entries),
            "games": sum(counter.values()),
            "entries": entries,
        }

    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dir": str(data_dir),
        "games_scanned": scanned,
        "games_skipped": skipped,
        "families": families,
        "notes": [
            "Whole observed configurations are sampled, weighted by how often they appear, "
            "so joint structure such as whether gains from trade exist is preserved.",
            "Games missing any defining field are skipped rather than imputed; the count is "
            "reported as games_skipped.",
        ],
    }
    out = ensure_dir(output_dir)
    write_json(out / "config_catalogue.json", payload)
    return payload


class ConfigCatalogue:
    """Samples real configurations, weighted by observed frequency."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self._configs: dict[str, list[dict[str, Any]]] = {}
        self._weights: dict[str, list[int]] = {}
        for family, block in (payload.get("families") or {}).items():
            entries = block.get("entries") or []
            if not entries:
                continue
            self._configs[family] = [entry["config"] for entry in entries]
            self._weights[family] = [int(entry.get("count") or 1) for entry in entries]

    @classmethod
    def load(cls, path: str | Path | None) -> "ConfigCatalogue | None":
        if not path:
            return None
        p = Path(path)
        if p.is_dir():
            p = p / "config_catalogue.json"
        if not p.exists():
            return None
        catalogue = cls(json.loads(p.read_text(encoding="utf-8")))
        return catalogue if catalogue._configs else None

    def has(self, family: str) -> bool:
        return bool(self._configs.get(family))

    def sample(self, family: str, rng: random.Random) -> dict[str, Any] | None:
        configs = self._configs.get(family)
        if not configs:
            return None
        chosen = rng.choices(configs, weights=self._weights[family], k=1)[0]
        return dict(chosen)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Catalogue the real GLEE game configurations.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="models/config_catalogue")
    args = parser.parse_args(argv)
    payload = build_config_catalogue(args.data_dir, args.output_dir)
    print(
        json.dumps(
            {
                "games_scanned": payload["games_scanned"],
                "games_skipped": payload["games_skipped"],
                "distinct_configs": {family: block["distinct_configs"] for family, block in payload["families"].items()},
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
