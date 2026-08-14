"""Validate every payload boundary against its contract, and report.

The point is to make the shape-mismatch class of bug something we *test for* on
each data refresh rather than something we discover months later from an
implausible metric. It checks:

* a sample of real ingested events, and the transcript rows inside them, against
  the offline contracts;
* the live fixtures against the live contracts, so a documented schema we have
  mis-transcribed shows up before any rated game is played.

Exit status is non-zero when anything is violated, so this can gate a refresh.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.contracts import (
    INGESTED_EVENT,
    TRANSCRIPT_DECISION_ROW,
    TRANSCRIPT_MESSAGE_ROW,
    TRANSCRIPT_QUALITY_ROW,
    ContractReport,
    Mode,
    enforce,
    live_contract,
)
from glee_eval.storage.trajectories import ensure_dir, write_json


def _sample_events(path: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Read `limit` events spread evenly across the file, by byte offset.

    Two earlier approaches were too slow to run on every test invocation. Counting
    the rows first cost a full 8.2 GB pass; striding with `iter_jsonl` still
    JSON-parsed all 1.19M lines just to skip most of them. Seeking to evenly spaced
    offsets touches only the rows we actually check.

    Sampling across the file rather than taking a prefix is what makes the check
    meaningful at all: events are grouped by family, so a prefix is entirely
    bargaining and reaches none of the persuasion transcript rows that broke.
    """

    events: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError:
        return events, 0
    if size <= 0 or limit <= 0:
        return events, size

    step = max(1, size // limit)
    with path.open("rb") as handle:
        for index in range(limit):
            offset = index * step
            if offset >= size:
                break
            handle.seek(offset)
            if offset:
                handle.readline()  # discard the partial line we landed inside
            line = handle.readline()
            if not line:
                break
            try:
                payload = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events, size


def check_offline(data_dir: str | Path = DEFAULT_DATA_DIR, *, limit: int = 20_000) -> dict[str, Any]:
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        return {"skipped": f"missing {events_path}", "clean": True}

    report = ContractReport()
    families: Counter = Counter()
    transcript_rows = 0
    sampled, file_size = _sample_events(events_path, limit)
    for event in sampled:
        families[str(event.get("game_family"))] += 1
        enforce(event, INGESTED_EVENT, mode=Mode.OBSERVE, report=report, context=str(event.get("game_id")))
        for row in event.get("transcript_so_far") or []:
            if not isinstance(row, dict):
                continue
            action_type = str(row.get("action_type") or "")
            if action_type == "nature_quality":
                transcript_rows += 1
                enforce(row, TRANSCRIPT_QUALITY_ROW, mode=Mode.OBSERVE, report=report)
            elif action_type == "message":
                # Text-mode seller pitches carry prose, not a yes/no.
                transcript_rows += 1
                enforce(row, TRANSCRIPT_MESSAGE_ROW, mode=Mode.OBSERVE, report=report)
            elif action_type in {"recommendation", "buy_decision"}:
                transcript_rows += 1
                enforce(row, TRANSCRIPT_DECISION_ROW, mode=Mode.OBSERVE, report=report)
    return {
        "events_scanned": len(sampled),
        "bytes_spanned": file_size,
        "transcript_rows_checked": transcript_rows,
        "families": dict(families),
        **report.to_dict(),
    }


def check_live() -> dict[str, Any]:
    from glee_eval.live import fixtures

    report = ContractReport()
    checked = 0
    for game in fixtures.sample_games():
        contract = live_contract(game.get("game_family"))
        if contract is None:
            continue
        checked += 1
        enforce(game, contract, mode=Mode.OBSERVE, report=report, context=str(game.get("game_id")))
    return {"fixtures_checked": checked, **report.to_dict()}


def schema_check(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/schema_check",
    *,
    limit: int = 20_000,
) -> dict[str, Any]:
    offline = check_offline(data_dir, limit=limit)
    live = check_live()
    report = {
        "schema_version": 1,
        "offline": offline,
        "live": live,
        "clean": bool(offline.get("clean", True)) and bool(live.get("clean", True)),
        "notes": [
            "A shadowed_by_alias violation is the dangerous one: the fact is present "
            "under a name we do not read, so nothing downstream raises -- it just "
            "quietly takes a default.",
            "Live payloads are checked against hand-built fixtures, so this proves our "
            "reading of the documented schema, not the server's actual behaviour.",
        ],
    }
    out = ensure_dir(output_dir)
    write_json(out / "schema_check.json", report)
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Validate all data boundaries against their contracts.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/schema_check")
    parser.add_argument("--limit", type=int, default=20_000)
    args = parser.parse_args(argv)

    report = schema_check(args.data_dir, args.output_dir, limit=args.limit)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["clean"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
