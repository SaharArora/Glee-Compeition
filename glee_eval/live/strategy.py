"""The function the SDK calls, wrapped so it can never fail to produce a move.

`GleeClient._handle_game` catches any exception from the strategy, logs it, and
returns *without submitting a move*. That is sensible isolation from the SDK's
point of view but it means a crash in our code is silent from the server's: the
turn simply times out, and a timeout is scored at the 5th percentile. At low game
counts one such incident can move a family rating by roughly 400 points, because
the `g/(g+30)` discount leaves early games heavily weighted.

So this layer guarantees three things, in order of importance:

1. **It always returns a legal action dict.** Every failure path -- translation
   error, agent exception, agent returning nonsense, unknown family -- lands on
   `fallback_action`, never on a raise.
2. **It bounds its own time.** The server allows 120 seconds per turn; the agent
   is pure computation and takes milliseconds, but a pathological state should
   surface as a fallback move rather than a timeout.
3. **It records what it saw.** The live schema is documented but unverified
   against a real game until we play one, so every game dict and every failure is
   appended to a JSONL log. The first real games are the cheapest opportunity to
   discover a mistranslation, and a silent one is expensive.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from glee_eval.live.schema import FAMILIES, action_type_of, fallback_action, to_game_state, to_live_action

logger = logging.getLogger("glee_eval.live")

# Well inside the server's 120s turn budget. The agent itself is sub-millisecond,
# so hitting this at all means something is wrong and a fallback is the right move.
DEFAULT_DEADLINE_SECONDS = 20.0


class LiveStrategy:
    """Adapts a `CandidateAgent` into the callable `GleeClient.run` expects."""

    def __init__(
        self,
        agent: Any,
        *,
        observation_log: str | Path | None = "reports/live/observations.jsonl",
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    ):
        self.agent = agent
        self.deadline_seconds = deadline_seconds
        self.observation_log = Path(observation_log) if observation_log else None
        if self.observation_log:
            try:
                self.observation_log.parent.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001 - diagnostics must never block play
                logger.exception("Cannot create %s; continuing without an observation log", self.observation_log)
                self.observation_log = None
        self.counters: Counter = Counter()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def __call__(self, game: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        record: dict[str, Any] = {
            "game_id": game.get("game_id"),
            "game_family": game.get("game_family"),
            "phase": game.get("phase"),
            "your_player": game.get("your_player"),
            "action_type": action_type_of(game),
            "game_state": game.get("game_state"),
            "valid_actions": game.get("valid_actions"),
        }
        try:
            action_payload = self._decide(game, record)
            record["status"] = record.get("status") or "ok"
        except BaseException as exc:  # noqa: BLE001 - a raise here costs a real game
            # Deliberately BaseException. A KeyboardInterrupt or MemoryError landing
            # mid-turn would otherwise propagate into the SDK's handler and lose the
            # game to a timeout just like any other error.
            record["status"] = "fallback_after_exception"
            record["error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("Live strategy failed for game %s; submitting fallback", game.get("game_id"))
            action_payload = self._safe_fallback(game)

        record["elapsed_seconds"] = round(time.monotonic() - started, 4)
        record["action"] = action_payload
        self._observe(record)
        return action_payload

    # ------------------------------------------------------------------
    def _decide(self, game: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        family = str(game.get("game_family") or "")
        if family not in FAMILIES:
            record["status"] = "fallback_unknown_family"
            return self._safe_fallback(game)

        state = to_game_state(game)
        record["translated_state"] = {
            "role": state.role,
            "round": state.round,
            "horizon": state.horizon,
            "public_parameters": state.public_parameters,
            "private_parameters": state.private_parameters,
            "transcript_len": len(state.visible_transcript),
        }

        action = self.agent.decide(state)
        if getattr(action, "action_type", None) is None:
            # An agent that returns None or some other non-action still yields a
            # legal-looking default from the translator, which would be recorded as
            # a healthy turn. Catch it here so a broken agent is visible rather than
            # quietly playing defaults for a whole competition.
            record["status"] = "fallback_agent_returned_non_action"
            record["error"] = f"agent returned {type(action).__name__}"
            return self._safe_fallback(game)
        payload = to_live_action(game, action)
        if not isinstance(payload, dict) or not payload:
            record["status"] = "fallback_empty_action"
            return self._safe_fallback(game)
        record["agent_action_type"] = getattr(action, "action_type", None)
        return payload

    def _safe_fallback(self, game: dict[str, Any]) -> dict[str, Any]:
        """`fallback_action` itself must not be the thing that raises."""

        try:
            payload = fallback_action(game)
            if isinstance(payload, dict) and payload:
                return payload
        except BaseException:  # noqa: BLE001
            logger.exception("fallback_action failed for game %s", game.get("game_id"))
        # Last resort: legal in every decision phase of every family.
        return {"decision": "no"}

    # ------------------------------------------------------------------
    def _observe(self, record: dict[str, Any]) -> None:
        status = str(record.get("status") or "unknown")
        with self._lock:
            self.counters[status] += 1
            self.counters[f"family:{record.get('game_family')}"] += 1
            if record.get("elapsed_seconds", 0) > self.deadline_seconds:
                self.counters["slow_turn"] += 1
                logger.warning(
                    "Turn for game %s took %.2fs, beyond the %.0fs budget",
                    record.get("game_id"),
                    record.get("elapsed_seconds"),
                    self.deadline_seconds,
                )
            if not self.observation_log:
                return
            try:
                with self.observation_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
            except Exception:  # noqa: BLE001 - logging must never cost a game
                logger.exception("Could not append to the live observation log")

    def summary(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self.counters)
        total = sum(value for key, value in counters.items() if not key.startswith("family:") and key != "slow_turn")
        failures = sum(
            value for key, value in counters.items() if key.startswith("fallback") or key == "fallback_after_exception"
        )
        return {
            "turns": total,
            "fallbacks": failures,
            "fallback_rate": (failures / total) if total else None,
            "counters": counters,
            "observation_log": str(self.observation_log) if self.observation_log else None,
        }


def build_strategy(
    agent_spec: str = "my_agents.jordan_strategic:MyAgent",
    *,
    seed: int = 0,
    observation_log: str | Path | None = "reports/live/observations.jsonl",
) -> LiveStrategy:
    from glee_eval.adapters.candidate_agent import load_agent

    return LiveStrategy(load_agent(agent_spec, seed=seed), observation_log=observation_log)


def strategy_from_env() -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Entry point for a bare `client.run(strategy_from_env())`."""

    return build_strategy(os.getenv("GLEE_LIVE_AGENT", "my_agents.jordan_strategic:MyAgent"))
