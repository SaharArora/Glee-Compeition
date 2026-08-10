from __future__ import annotations

from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.schemas import GameState
from glee_eval.storage.trajectories import read_records, write_jsonl


def _valid_schema(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("action_type") in {"offer", "message", "recommendation"}:
        return {"kind": "offer" if event.get("action_type") == "offer" else "recommendation"}
    if event.get("action_type") == "buy_decision":
        return {"kind": "buy_decision"}
    return {"kind": "decision"}


def state_from_event(event: dict[str, Any]) -> GameState:
    config = event.get("configuration") or {}
    horizon = int(config.get("max_rounds") or config.get("total_rounds") or 0)
    historical = {
        "action_type": event.get("action_type"),
        "numeric_action": event.get("numeric_action"),
        "free_text_message": event.get("free_text_message"),
        "accept_reject": "accept" if event.get("accepted") else "reject" if event.get("rejected") else None,
        "buy_no_buy": "yes" if event.get("bought") else "no" if event.get("bought") is False else None,
        "raw_record": event.get("raw_record"),
    }
    return GameState(
        scenario_id=f"probe-{event.get('game_id')}",
        game_id=str(event.get("game_id")),
        game_family=str(event.get("game_family")),
        role=str(event.get("role")),
        round=int(event.get("round") or 0),
        horizon=horizon,
        public_parameters=event.get("public_parameters") or {},
        private_parameters=event.get("private_information") or {},
        visible_transcript=event.get("transcript_so_far") or [],
        valid_action_schema=_valid_schema(event),
        metadata={
            "historical_action": historical,
            "terminal_outcome": event.get("terminal_outcome"),
            "source": event.get("source"),
            "config_id": event.get("config_id"),
        },
    )


def extract_probes(
    events: list[dict[str, Any]],
    family: str | None = None,
    limit: int | None = None,
    include_nature: bool = False,
) -> list[GameState]:
    probes: list[GameState] = []
    for event in events:
        if family and event.get("game_family") != family:
            continue
        if not include_nature and event.get("role") == "nature":
            continue
        if event.get("action_type") == "nature_quality":
            continue
        probes.append(state_from_event(event))
        if limit is not None and len(probes) >= limit:
            break
    return probes


def extract_from_processed(data_dir: str | Path = DEFAULT_DATA_DIR, family: str | None = None, limit: int | None = None) -> list[GameState]:
    events = read_records(Path(data_dir) / "processed" / "events.jsonl")
    probes = extract_probes(events, family=family, limit=limit)
    out = Path(data_dir) / "processed" / "probes.jsonl"
    write_jsonl(out, probes)
    return probes

