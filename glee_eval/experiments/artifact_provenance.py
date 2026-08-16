from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def artifact_provenance(path: str | Path | None, filename: str) -> dict[str, Any]:
    """Resolve an input artifact and freeze its exact bytes in run provenance."""

    if path is None:
        return {"path": None, "sha256": None}
    resolved = Path(path)
    if resolved.is_dir():
        resolved = resolved / filename
    if not resolved.is_file():
        raise FileNotFoundError(f"Missing experiment artifact: {resolved}")
    return {
        "path": str(resolved.resolve()),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }
