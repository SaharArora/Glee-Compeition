from __future__ import annotations

import csv
import json
import os
import tempfile
import hashlib
from pathlib import Path
from typing import Any, Iterable

from glee_eval.data.schemas import to_jsonable


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, payload: Any) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def write_json_atomic(path: str | Path, payload: Any) -> Path:
    """Write complete JSON beside its destination, then atomically replace it."""
    p = Path(path)
    ensure_dir(p.parent)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=p.parent,
                                         prefix=f".{p.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, default=to_jsonable)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, p)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return p


def canonical_json_sha256(payload: Any) -> str:
    """Hash canonical JSON incrementally without materializing canonical bytes."""
    digest=hashlib.sha256()
    encoder=json.JSONEncoder(sort_keys=True,separators=(",",":"),default=to_jsonable)
    for chunk in encoder.iterencode(payload):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, records: Iterable[Any]) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(to_jsonable(record), sort_keys=True) + "\n")
    return p


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_csv(path: str | Path, records: list[dict[str, Any]]) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    if not records:
        p.write_text("", encoding="utf-8")
        return p
    fieldnames = sorted({key for record in records for key in record.keys()})
    with p.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {}
            for key in fieldnames:
                value = record.get(key)
                row[key] = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
            writer.writerow(row)
    return p


def write_table_bundle(path_without_suffix: str | Path, records: list[dict[str, Any]]) -> dict[str, str | None]:
    """Write records as JSONL/CSV and Parquet when optional dependencies exist."""

    base = Path(path_without_suffix)
    ensure_dir(base.parent)
    jsonl = write_jsonl(base.with_suffix(".jsonl"), records)
    csv_path = write_csv(base.with_suffix(".csv"), records)
    parquet_path: Path | None = None
    parquet_error: str | None = None
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame([to_jsonable(record) for record in records])
        candidate = base.with_suffix(".parquet")
        frame.to_parquet(candidate, index=False)
        parquet_path = candidate
    except Exception as exc:  # pragma: no cover - depends on optional local deps.
        parquet_error = f"{type(exc).__name__}: {exc}"
    return {
        "jsonl": str(jsonl),
        "csv": str(csv_path),
        "parquet": str(parquet_path) if parquet_path else None,
        "parquet_error": parquet_error,
    }


def read_records(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if p.suffix == ".jsonl":
        return read_jsonl(p)
    if p.suffix == ".json":
        payload = read_json(p)
        return payload if isinstance(payload, list) else payload.get("records", [])
    if p.suffix == ".csv":
        with p.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    if p.suffix == ".parquet":
        import pandas as pd  # type: ignore

        return pd.read_parquet(p).to_dict("records")
    raise ValueError(f"Unsupported records format: {p}")
