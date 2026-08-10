from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from glee_eval.config import DEFAULT_GLEE_ROOT


@dataclass(frozen=True)
class OfficialAdapterStatus:
    available: bool
    reason: str
    glee_root: str


def check_official_adapter(glee_root: str | Path = DEFAULT_GLEE_ROOT) -> OfficialAdapterStatus:
    root = Path(glee_root)
    required = [
        root / "games" / "bargaining" / "bargaining.py",
        root / "games" / "negotiation" / "negotiation.py",
        root / "games" / "persuasion" / "persuasion.py",
        root / "players" / "base_player.py",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        return OfficialAdapterStatus(False, f"Missing required files: {missing}", str(root))
    return OfficialAdapterStatus(True, "Official GLEE source files are available for adapter-level wrapping.", str(root))


@contextlib.contextmanager
def glee_import_context(glee_root: str | Path = DEFAULT_GLEE_ROOT):
    root = Path(glee_root).resolve()
    old_cwd = Path.cwd()
    inserted = False
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
        inserted = True
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(old_cwd)
        if inserted:
            with contextlib.suppress(ValueError):
                sys.path.remove(str(root))


class InMemoryLogger:
    """Small logger implementing the subset of GLEE DataLogger used by game classes."""

    def __init__(self, game_id: str = "in_memory", **args: Any):
        self.game_id = game_id
        self.args = args
        self.actions: list[dict[str, Any]] = []
        self.saved = False

    def add_action(self, **kwargs: Any) -> None:
        data = dict(kwargs["data"])
        data["player"] = kwargs["player_name"]
        data["round"] = kwargs["round_number"]
        self.actions.append(data)

    def save(self) -> None:
        self.saved = True

    def _get_output_path(self) -> str:
        return "."

    def _save_partial_logs(self) -> None:
        return None


def import_official_games(glee_root: str | Path = DEFAULT_GLEE_ROOT) -> dict[str, Any]:
    with glee_import_context(glee_root):
        from games.bargaining.bargaining import BargainingGame
        from games.negotiation.negotiation import NegotiationGame
        from games.persuasion.persuasion import PersuasionGame
        from players.base_player import Player

    return {
        "BargainingGame": BargainingGame,
        "NegotiationGame": NegotiationGame,
        "PersuasionGame": PersuasionGame,
        "Player": Player,
    }

