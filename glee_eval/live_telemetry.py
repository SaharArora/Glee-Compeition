"""Attributable, fail-closed telemetry for the frozen Jordan live canary.

This is deliberately a separate launcher from :mod:`glee_eval.live.run`.  It
wraps the existing strategy and SDK boundaries without changing the policy or
the legacy live path.  No function in this module starts a game unless
``launch_canary`` (or the ``launch`` CLI subcommand) is called explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.metadata
import json
import logging
import math
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from glee_eval.live.strategy import build_strategy

FROZEN_CANDIDATE_COMMIT = "bce578597dbfacf2ebca38399edb41a5dde2f936"
FROZEN_AGENT_SPEC = "my_agents.jordan_strategic:MyAgent"
FROZEN_AGENT_UUID = "99357c15-48d5-4177-9d6a-48d02b95a164"
FROZEN_AGENT_NAME = "gangsteryoshi"
FROZEN_POLICY_PATH = "my_agents/jordan_strategic.py"
FROZEN_POLICY_SHA256 = "27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82"
FAMILIES = ("bargaining", "negotiation", "persuasion")
ARTIFACT_ENV = (
    "GLEE_OPPONENT_POPULATION",
    "GLEE_CONFIG_CATALOGUE",
    "GLEE_RESPONSE_MODEL",
    "GLEE_SUPPORT_INDEX",
)
NONSECRET_ENV = ("GLEE_LIVE_AGENT", "PYTHONHASHSEED")
SECRET_ENV = ("GLEE_API_KEY",)
SCHEMA = "glee.live.telemetry.v1"

ClientT = TypeVar("ClientT")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_bytes(value))


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=text
    )
    return completed.stdout


def _repo_root(path: str | Path = ".") -> Path:
    return Path(str(_git(Path(path), "rev-parse", "--show-toplevel")).strip()).resolve()


def capture_git_state(repo: str | Path = ".") -> dict[str, Any]:
    """Return exact HEAD and a deterministic digest of all tracked/untracked edits.

    The digest covers the binary Git diff from HEAD plus the path, mode and bytes
    of every non-ignored untracked file.  It therefore distinguishes clean from
    dirty and is stable across status display ordering and wall-clock time.
    """

    root = _repo_root(repo)
    head = str(_git(root, "rev-parse", "HEAD")).strip()
    tracked_diff = bytes(_git(root, "diff", "--binary", "--full-index", "HEAD", text=False))
    untracked_raw = bytes(_git(root, "ls-files", "--others", "--exclude-standard", "-z", text=False))
    untracked: list[dict[str, Any]] = []
    for raw in sorted(part for part in untracked_raw.split(b"\0") if part):
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = root / relative
        if path.is_symlink():
            payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            kind = "symlink"
        elif path.is_file():
            payload = path.read_bytes()
            kind = "file"
        else:
            payload = b""
            kind = "other"
        untracked.append({"path": relative, "kind": kind, "sha256": _sha256(payload)})
    digest_input = {
        "tracked_diff_sha256": _sha256(tracked_diff),
        "untracked": untracked,
    }
    dirty = bool(tracked_diff or untracked)
    return {
        "repo_root": str(root),
        "head": head,
        "dirty": dirty,
        "dirty_digest": _sha256(_canonical_bytes(digest_input)),
        "tracked_diff_sha256": digest_input["tracked_diff_sha256"],
        "untracked": untracked,
    }


def verify_frozen_policy(repo: str | Path, candidate_commit: str = FROZEN_CANDIDATE_COMMIT) -> dict[str, Any]:
    root = _repo_root(repo)
    commit = str(_git(root, "rev-parse", f"{candidate_commit}^{{commit}}")).strip()
    if commit != candidate_commit:
        raise RuntimeError(f"candidate commit resolved to {commit}, expected {candidate_commit}")
    frozen = bytes(_git(root, "show", f"{candidate_commit}:{FROZEN_POLICY_PATH}", text=False))
    current_path = root / FROZEN_POLICY_PATH
    frozen_sha = _sha256(frozen)
    current_sha = _sha256_file(current_path)
    if frozen_sha != FROZEN_POLICY_SHA256 or current_sha != frozen_sha:
        raise RuntimeError(
            f"Jordan policy mismatch: frozen={frozen_sha}, current={current_sha}, "
            f"required={FROZEN_POLICY_SHA256}"
        )
    return {
        "candidate_commit": candidate_commit,
        "entrypoint": FROZEN_AGENT_SPEC,
        "policy_path": FROZEN_POLICY_PATH,
        "policy_sha256": current_sha,
        "matches_candidate_commit": True,
    }


def _secret_hmac(value: str, key: bytes, name: str) -> str:
    return hmac.new(key, name.encode() + b"\0" + value.encode(), hashlib.sha256).hexdigest()


def capture_environment(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Capture relevant environment identity while never serialising a secret.

    Secret values use a keyed HMAC.  The key is required when a secret is
    present, is never written, and is represented only by a one-way key ID.
    Low-entropy non-secret values use a domain-separated SHA-256.  Artifact
    variables additionally hash the file bytes when the path exists.
    """

    environ = dict(os.environ if env is None else env)
    hmac_key_raw = environ.get("GLEE_TELEMETRY_HMAC_KEY")
    if any(environ.get(name) for name in SECRET_ENV) and not hmac_key_raw:
        raise RuntimeError("GLEE_TELEMETRY_HMAC_KEY is required to fingerprint live credentials safely")
    hmac_key = hmac_key_raw.encode() if hmac_key_raw else b""
    if hmac_key and len(hmac_key) < 32:
        raise RuntimeError("GLEE_TELEMETRY_HMAC_KEY must contain at least 32 bytes")

    variables: dict[str, Any] = {}
    for name in SECRET_ENV:
        value = environ.get(name)
        variables[name] = {
            "present": value is not None,
            "classification": "secret",
            "value_hmac_sha256": _secret_hmac(value, hmac_key, name) if value is not None else None,
            "redacted": True,
        }
    for name in NONSECRET_ENV:
        value = environ.get(name)
        variables[name] = {
            "present": value is not None,
            "classification": "configuration",
            "value_sha256": _sha256((name + "\0" + value).encode()) if value is not None else None,
        }
    artifacts: dict[str, Any] = {}
    for name in ARTIFACT_ENV:
        value = environ.get(name)
        row: dict[str, Any] = {"configured": bool(value)}
        if value:
            path = Path(value).expanduser().resolve()
            row.update({
                "path": str(path),
                "path_sha256": _sha256((name + "\0" + str(path)).encode()),
                "exists": path.is_file(),
                "artifact_sha256": _sha256_file(path) if path.is_file() else None,
            })
        artifacts[name] = row
    try:
        sdk_version = importlib.metadata.version("glee-sdk")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = "unavailable"
    return {
        "variables": variables,
        "artifacts": artifacts,
        "secret_hmac_key_id": _sha256(hmac_key) if hmac_key else None,
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform_sha256": _sha256(platform.platform().encode()),
            "glee_sdk_version": sdk_version,
        },
    }


def _redact(value: Any, secret_values: Sequence[str] = ()) -> Any:
    """Recursively redact fields whose names could carry credentials."""

    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("token", "secret", "password", "api_key", "credential", "auth")):
                clean[str(key)] = "<redacted>"
            else:
                clean[str(key)] = _redact(item, secret_values)
        return clean
    if isinstance(value, (list, tuple)):
        return [_redact(item, secret_values) for item in value]
    if isinstance(value, str):
        clean_text = value
        for secret in secret_values:
            if secret:
                clean_text = clean_text.replace(secret, "<redacted-secret-value>")
        return clean_text
    return value


def _walk_dict(value: Any, prefix: str = "") -> list[tuple[str, str, Any]]:
    rows: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.append((path, str(key).lower(), item))
            rows.extend(_walk_dict(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_walk_dict(item, f"{prefix}[{index}]"))
    return rows


OFFICIAL_ALIASES = {
    "percentile": ("official_percentile", "percentile"),
    # A generic result.rating is ambiguous: captured historical payloads do not
    # establish that it is the official per-game rating rather than an aggregate.
    "game_rating": ("official_game_rating", "game_rating"),
    "rating_update": ("official_rating_update", "rating_update", "rating_delta"),
    "public_opponent_adjustment": (
        "official_opponent_adjustment", "public_opponent_adjustment", "opponent_adjustment"
    ),
}


def official_scoring_capability(payload: Any) -> dict[str, Any]:
    walked = _walk_dict(payload)
    result: dict[str, Any] = {}
    for field, aliases in OFFICIAL_ALIASES.items():
        found = next((
            (path, value) for path, key, value in walked if key in aliases
            and (
                key.startswith("official_")
                or key in ("game_rating", "rating_update", "rating_delta", "public_opponent_adjustment")
                or path == f"result.{key}"
                or ".result." in path
            )
        ), None)
        result[field] = (
            {"status": "available", "value": _redact(found[1]), "source": found[0]}
            if found else {"status": "unavailable", "value": None, "source": None}
        )
    return result


def _identity_from_stats(stats: Any) -> dict[str, Any]:
    walked = _walk_dict(stats)
    uuid_keys = ("agent_uuid", "agent_id", "uuid", "id")
    name_keys = ("agent_name", "name")
    uuid_hit = next(
        ((path, value) for preferred in uuid_keys for path, key, value in walked if key == preferred), None
    )
    name_hit = next(
        ((path, value) for preferred in name_keys for path, key, value in walked if key == preferred), None
    )
    return {
        "uuid": str(uuid_hit[1]) if uuid_hit else None,
        "uuid_source": uuid_hit[0] if uuid_hit else None,
        "name": str(name_hit[1]) if name_hit else None,
        "name_source": name_hit[0] if name_hit else None,
        "capability": "available" if uuid_hit and name_hit else "unavailable",
    }


def _payoff_from(payload: Any) -> Any:
    for _, key, value in _walk_dict(payload):
        if key in ("payoff", "agent_payoff", "your_payoff", "normalized_payoff"):
            return _redact(value)
    return None


class TelemetryRecorder:
    """Append-only, fsync'd JSONL event ledger with batch/config linkage."""

    def __init__(
        self, path: str | Path, *, batch_id: str, configuration_sha256: str,
        secret_values: Sequence[str] = (),
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_id = batch_id
        self.configuration_sha256 = configuration_sha256
        self._secret_values = tuple(value for value in secret_values if value)
        self._sequence = 0
        self._previous_event_sha256: str | None = None
        self._lock = threading.Lock()

    def append(self, event_type: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            row = {
                "schema": SCHEMA,
                "batch_id": self.batch_id,
                "configuration_sha256": self.configuration_sha256,
                "sequence": self._sequence,
                "timestamp_utc": _utc_now(),
                "event_type": event_type,
                "previous_event_sha256": self._previous_event_sha256,
                **_redact(fields, self._secret_values),
            }
            row["event_sha256"] = _sha256(_canonical_bytes(row))
            with self.path.open("ab") as handle:
                handle.write(_canonical_bytes(row))
                handle.flush()
                os.fsync(handle.fileno())
            self._previous_event_sha256 = row["event_sha256"]
            return row


class TelemetryStrategy:
    """Observe exact scenarios/actions around the frozen existing strategy."""

    def __init__(self, base: Callable[[dict[str, Any]], dict[str, Any]], recorder: TelemetryRecorder):
        self.base = base
        self.recorder = recorder
        self._attempts: Counter[str] = Counter()
        self.fallbacks_by_family: Counter[str] = Counter()
        self._lock = threading.Lock()

    def __call__(self, game: dict[str, Any]) -> dict[str, Any]:
        started = _utc_now()
        game_id = str(game.get("game_id") or "")
        with self._lock:
            self._attempts[game_id] += 1
            attempt = self._attempts[game_id]
        state = game.get("game_state") if isinstance(game.get("game_state"), dict) else {}
        scenario = game.get("scenario_id") or state.get("scenario_id") or game_id
        family = game.get("game_family")
        role = game.get("your_player") or state.get("current_player") or state.get("role")
        try:
            before_summary = self.summary()
            action = self.base(game)
            after_summary = self.summary()
        except BaseException as exc:  # pragma: no cover - base strategy is already fail-safe
            self.recorder.append(
                "strategy_crash", game_id=game_id, family=family, role=role,
                error_type=type(exc).__name__, error=str(exc), attempt=attempt,
            )
            raise
        fallback = int(after_summary.get("fallbacks") or 0) > int(before_summary.get("fallbacks") or 0)
        if fallback:
            with self._lock:
                self.fallbacks_by_family[str(family)] += 1
        self.recorder.append(
            "action_prepared",
            game_id=game_id,
            scenario_id=scenario,
            scenario_sha256=_sha256(_canonical_bytes(game)),
            scenario=_redact(game),
            family=family,
            role=role,
            action=_redact(action),
            action_prepared_at=started,
            attempt=attempt,
            fallback=fallback,
        )
        return action

    def summary(self) -> dict[str, Any]:
        summary = getattr(self.base, "summary", None)
        return summary() if callable(summary) else {}


def telemetry_client_class(base: type[ClientT]) -> type[ClientT]:
    """Instrument SDK move/backfill boundaries without changing SDK control flow."""

    class TelemetryClient(base):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, telemetry_recorder: TelemetryRecorder, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self.telemetry_recorder = telemetry_recorder
            self._seen_game_ids: set[str] = set()
            self._terminal_game_ids: set[str] = set()
            self._context: dict[str, dict[str, Any]] = {}
            self._lock = threading.Lock()
            self.terminal_records: list[dict[str, Any]] = []
            self.counters: Counter[str] = Counter()

        def register_context(self, game: dict[str, Any]) -> None:
            game_id = str(game.get("game_id") or "")
            state = game.get("game_state") if isinstance(game.get("game_state"), dict) else {}
            context = {
                "game_id": game_id,
                "scenario_id": game.get("scenario_id") or state.get("scenario_id") or game_id,
                "family": game.get("game_family"),
                "role": game.get("your_player") or state.get("current_player") or state.get("role"),
            }
            with self._lock:
                prior = self._context.get(game_id)
                if prior and (prior.get("family"), prior.get("scenario_id")) != (
                    context.get("family"), context.get("scenario_id")
                ):
                    self.counters["duplicate_conflicts"] += 1
                    self.telemetry_recorder.append("duplicate_game_conflict", prior=prior, observed=context)
                self._context[game_id] = context

        def _safe_stats(self, boundary: str, game_id: str) -> dict[str, Any] | None:
            try:
                value = self.stats()
                self.telemetry_recorder.append(
                    "platform_stats_snapshot", boundary=boundary, game_id=game_id,
                    stats=_redact(value), scoring_capability=official_scoring_capability(value),
                )
                return value
            except Exception as exc:  # noqa: BLE001 - telemetry cannot suppress a move
                self.counters["stats_errors"] += 1
                self.telemetry_recorder.append(
                    "platform_stats_unavailable", boundary=boundary, game_id=game_id,
                    error_type=type(exc).__name__, error=str(exc),
                )
                return None

        def move(self, game_id: str, action: dict[str, Any]) -> dict[str, Any]:
            context = self._context.get(game_id, {"game_id": game_id})
            before = self._safe_stats("before_move", game_id)
            self.telemetry_recorder.append("move_started", **context, action=_redact(action))
            try:
                response = super().move(game_id, action)
            except TimeoutError as exc:
                self.counters["timeouts"] += 1
                self.counters[f"timeout_family:{context.get('family')}"] += 1
                self.telemetry_recorder.append(
                    "move_timeout", **context, error_type=type(exc).__name__, error=str(exc)
                )
                raise
            except Exception as exc:
                self.counters["api_failures"] += 1
                self.counters[f"api_failure_family:{context.get('family')}"] += 1
                self.telemetry_recorder.append(
                    "move_api_failure", **context, error_type=type(exc).__name__, error=str(exc)
                )
                raise
            terminal = bool(response.get("game_over")) if isinstance(response, dict) else False
            valid = response.get("valid") if isinstance(response, dict) else None
            after = self._safe_stats("after_terminal" if terminal else "after_move", game_id)
            official = official_scoring_capability(response)
            row = {
                **context,
                "action": _redact(action),
                "valid": valid,
                "terminal": terminal,
                "terminal_status": "terminal" if terminal else "active",
                "payoff": _payoff_from(response),
                "result": _redact(response.get("result")) if isinstance(response, dict) else None,
                "official_scoring": official,
                "platform_stats_before": _redact(before),
                "platform_stats_after": _redact(after),
                "response": _redact(response),
                "source": "move_response",
            }
            self.telemetry_recorder.append("move_result", **row)
            with self._lock:
                self._seen_game_ids.add(game_id)
                self.counters["moves"] += 1
                if valid is False:
                    self.counters["invalid_moves"] += 1
                    self.counters[f"invalid_family:{context.get('family')}"] += 1
                if terminal:
                    if game_id in self._terminal_game_ids:
                        self.counters["duplicate_terminals"] += 1
                        self.telemetry_recorder.append("duplicate_terminal", **context)
                    else:
                        self._terminal_game_ids.add(game_id)
                        self.terminal_records.append(row)
            return response

        def backfill_terminal_results(self, game_ids: Sequence[str] | None = None) -> None:
            targets = set(game_ids) if game_ids is not None else set(self._seen_game_ids)
            for game_id in sorted(targets - self._terminal_game_ids):
                context = self._context.get(game_id, {"game_id": game_id})
                self.counters["backfill_attempts"] += 1
                try:
                    response = self.game_state(game_id)
                    terminal = bool(response.get("game_over")) if isinstance(response, dict) else False
                    terminal = terminal or (isinstance(response, dict) and response.get("result") is not None)
                    row = {
                        **context,
                        "action": None,
                        "valid": None,
                        "terminal": terminal,
                        "terminal_status": "terminal" if terminal else "unresolved",
                        "payoff": _payoff_from(response),
                        "result": _redact(response.get("result")) if isinstance(response, dict) else None,
                        "official_scoring": official_scoring_capability(response),
                        "response": _redact(response),
                        "source": "game_state_backfill",
                    }
                    self.telemetry_recorder.append("terminal_backfill", **row)
                    if terminal:
                        with self._lock:
                            self._terminal_game_ids.add(game_id)
                            self.terminal_records.append(row)
                except Exception as exc:  # noqa: BLE001 - preserve partial batch and stop
                    self.counters["backfill_failures"] += 1
                    self.telemetry_recorder.append(
                        "backfill_failure", **context, error_type=type(exc).__name__, error=str(exc)
                    )

    TelemetryClient.__name__ = f"AttributableTelemetry{base.__name__}"
    return TelemetryClient


def _mean_bound(values: Sequence[float], *, upper: bool) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean
    half = 1.645 * statistics.stdev(values) / math.sqrt(len(values))
    return mean + half if upper else mean - half


def evaluate_stop_rules(
    terminals: Sequence[Mapping[str, Any]], counters: Mapping[str, int],
    fallbacks_by_family: Mapping[str, int] | None = None,
    *, require_official_scoring: bool = True,
) -> dict[str, Any]:
    """Evaluate the frozen prospective canary stop rules from captured records."""

    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    unavailable: list[str] = []
    for row in terminals:
        family = str(row.get("family") or "unknown")
        by_family[family].append(row)
        capability = row.get("official_scoring") if isinstance(row.get("official_scoring"), dict) else {}
        if not isinstance(capability.get("game_rating"), dict) or capability["game_rating"].get("status") != "available":
            unavailable.append(str(row.get("game_id")))
    reasons: list[str] = []
    if counters.get("duplicate_terminals", 0) or counters.get("duplicate_conflicts", 0):
        reasons.append("duplicate_or_conflicting_game")
    if require_official_scoring and unavailable:
        reasons.append("official_per_game_rating_unavailable")
    fallbacks_by_family = fallbacks_by_family or {}
    for family in FAMILIES:
        invalid_or_fallback = counters.get(f"invalid_family:{family}", 0) + fallbacks_by_family.get(family, 0)
        if invalid_or_fallback >= 3:
            reasons.append(f"three_invalid_or_fallback:{family}")
        family_failures = counters.get(f"api_failure_family:{family}", 0) + counters.get(f"timeout_family:{family}", 0)
        if family_failures >= 3:
            reasons.append(f"three_timeout_or_api_failures:{family}")

    paused: dict[str, str] = {}
    upper_bounds: dict[str, float | None] = {}
    for family, rows in by_family.items():
        ratings = [
            float(row["official_scoring"]["game_rating"]["value"])
            for row in rows
            if isinstance(row.get("official_scoring"), dict)
            and isinstance(row["official_scoring"].get("game_rating"), dict)
            and row["official_scoring"]["game_rating"].get("status") == "available"
            and isinstance(row["official_scoring"]["game_rating"].get("value"), (int, float))
        ]
        upper_bounds[family] = _mean_bound(ratings, upper=True)
        if len(ratings) >= 30 and upper_bounds[family] is not None and upper_bounds[family] < 1800:
            paused[family] = "one_sided_95pct_upper_bound_below_1800"
    if len(paused) >= 2:
        reasons.append("two_families_below_1800")
    pooled = [value for rows in by_family.values() for row in rows for value in [
        row.get("official_scoring", {}).get("game_rating", {}).get("value")
        if isinstance(row.get("official_scoring"), dict) else None
    ] if isinstance(value, (int, float))]
    pooled_upper = _mean_bound([float(value) for value in pooled], upper=True)
    if all(len(by_family.get(family, [])) >= 30 for family in FAMILIES) and pooled_upper is not None and pooled_upper < 1800:
        reasons.append("pooled_upper_bound_below_1800")
    return {
        "global_stop": bool(reasons),
        "reasons": sorted(set(reasons)),
        "paused_families": paused,
        "official_game_rating_unavailable_game_ids": sorted(unavailable),
        "family_upper_bounds": upper_bounds,
        "pooled_upper_bound": pooled_upper,
    }


def build_configuration_manifest(
    repo: str | Path, *, env: Mapping[str, str], families: Sequence[str],
    per_family_games: int, concurrency: int, allow_dirty: bool = False,
) -> dict[str, Any]:
    git_state = capture_git_state(repo)
    if git_state["dirty"] and not allow_dirty:
        raise RuntimeError(f"refusing launch from dirty tree {git_state['dirty_digest']}")
    policy = verify_frozen_policy(repo)
    environment = capture_environment(env)
    if any(environment["artifacts"][name]["configured"] for name in ARTIFACT_ENV):
        raise RuntimeError("frozen Jordan contract requires all optional model artifact variables absent")
    return {
        "schema": "glee.live.configuration.v1",
        "git": git_state,
        "candidate": policy,
        "agent_identity_expected": {"uuid": FROZEN_AGENT_UUID, "name": FROZEN_AGENT_NAME},
        "families": list(families),
        "per_family_games": per_family_games,
        "total_games": per_family_games * len(families),
        "concurrency": concurrency,
        "environment": environment,
        "stop_contract": {
            "terminal_capture": "100%",
            "invalid_or_fallback": "at most 1%; global stop at three in any family",
            "timeouts_or_api_failures": "at most 2%; pause family at three",
            "attribution_failure": "immediate global stop",
            "performance_pause": "after n>=30, one-sided 95% UCB mean official game rating <1800",
            "success": "all terminals and each family one-sided 95% LCB mean official game rating >=2000",
        },
    }


def _read_events(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid event JSON at line {number}: {exc}") from exc
    return rows


def reconcile_batch(output_dir: str | Path, *, write: bool = True) -> dict[str, Any]:
    """Rebuild batch completeness from raw manifest/events; never trust summary counters."""

    out = Path(output_dir)
    launch = json.loads((out / "launch_manifest.json").read_text(encoding="utf-8"))
    config = launch["configuration"]
    config_sha = _sha256(_canonical_bytes(config))
    events = _read_events(out / "telemetry.jsonl")
    errors: list[str] = []
    if config_sha != launch.get("configuration_sha256"):
        errors.append("configuration_hash_mismatch")
    if any(row.get("batch_id") != launch.get("batch_id") for row in events):
        errors.append("batch_id_mismatch")
    if any(row.get("configuration_sha256") != config_sha for row in events):
        errors.append("event_configuration_mismatch")
    sequences = [row.get("sequence") for row in events]
    if sequences != list(range(1, len(events) + 1)):
        errors.append("noncontiguous_event_sequence")
    previous_hash: str | None = None
    for row in events:
        claimed = row.get("event_sha256")
        unhashed = dict(row)
        unhashed.pop("event_sha256", None)
        if row.get("previous_event_sha256") != previous_hash or claimed != _sha256(_canonical_bytes(unhashed)):
            errors.append("event_hash_chain_mismatch")
            break
        previous_hash = str(claimed)
    terminals = [row for row in events if row.get("event_type") in ("move_result", "terminal_backfill") and row.get("terminal")]
    terminal_ids = [str(row.get("game_id")) for row in terminals]
    duplicates = sorted(game_id for game_id, count in Counter(terminal_ids).items() if count > 1)
    if duplicates:
        errors.append("duplicate_terminal_game")
    actions = {str(row.get("game_id")) for row in events if row.get("event_type") == "action_prepared"}
    missing_actions = sorted(set(terminal_ids) - actions)
    if missing_actions:
        errors.append("terminal_without_captured_action")
    family_counts = Counter(str(row.get("family")) for row in terminals)
    expected_each = int(config["per_family_games"])
    expected_families = list(config["families"])
    required_missing: dict[str, list[str]] = {}
    for row in terminals:
        missing = [field for field in ("game_id", "family", "role", "terminal_status", "timestamp_utc") if row.get(field) is None]
        if row.get("payoff") is None:
            missing.append("payoff")
        if missing:
            required_missing[str(row.get("game_id"))] = missing
    if required_missing:
        errors.append("required_terminal_fields_missing")
    official_unavailable = sorted(
        str(row.get("game_id")) for row in terminals
        if row.get("official_scoring", {}).get("game_rating", {}).get("status") != "available"
    )
    action_rows = [row for row in events if row.get("event_type") == "action_prepared"]
    fallback_counts = Counter(str(row.get("family")) for row in action_rows if row.get("fallback") is True)
    invalid_counts = Counter(
        str(row.get("family")) for row in events
        if row.get("event_type") == "move_result" and row.get("valid") is False
    )
    fatal_event_types = {
        "batch_crash", "cap_violation", "duplicate_game_conflict", "duplicate_terminal",
        "move_api_failure", "move_timeout", "backfill_failure", "unresolved_terminal_stop",
        "preflight_failure",
    }
    fatal_events = [row.get("event_type") for row in events if row.get("event_type") in fatal_event_types]
    if fatal_events:
        errors.append("fatal_runtime_event")
    lower_bounds: dict[str, float | None] = {}
    for family in expected_families:
        ratings = [
            float(row["official_scoring"]["game_rating"]["value"])
            for row in terminals if row.get("family") == family
            and isinstance(row.get("official_scoring", {}).get("game_rating", {}).get("value"), (int, float))
        ]
        lower_bounds[family] = _mean_bound(ratings, upper=False)
    exact_counts = all(family_counts.get(family, 0) == expected_each for family in expected_families)
    complete = exact_counts and len(set(terminal_ids)) == expected_each * len(expected_families)
    status = "invalid" if errors else ("complete" if complete else "partial")
    report = {
        "schema": "glee.live.reconciliation.v1",
        "created_at": _utc_now(),
        "batch_id": launch.get("batch_id"),
        "configuration_sha256": config_sha,
        "status": status,
        "event_count": len(events),
        "unique_terminal_games": len(set(terminal_ids)),
        "family_terminal_counts": dict(sorted(family_counts.items())),
        "expected_per_family": expected_each,
        "duplicate_terminal_game_ids": duplicates,
        "missing_action_game_ids": missing_actions,
        "required_terminal_fields_missing": required_missing,
        "official_game_rating_unavailable_game_ids": official_unavailable,
        "fallback_counts": dict(sorted(fallback_counts.items())),
        "invalid_move_counts": dict(sorted(invalid_counts.items())),
        "fatal_runtime_events": fatal_events,
        "family_game_rating_lower_95pct": lower_bounds,
        "errors": errors,
        "attributable_for_official_canary": status == "complete" and not official_unavailable,
        "success_for_expansion": (
            status == "complete" and not official_unavailable
            and all(lower_bounds.get(family) is not None and lower_bounds[family] >= 2000 for family in expected_families)
            and all(fallback_counts.get(family, 0) + invalid_counts.get(family, 0) <= 1 for family in expected_families)
        ),
    }
    if write:
        _write_json(out / "reconciliation.json", report)
    return report


def _validate_identity(stats: Any) -> dict[str, Any]:
    identity = _identity_from_stats(stats)
    if identity["capability"] != "available":
        raise RuntimeError("platform stats do not expose an attributable agent UUID and name")
    if identity["uuid"] != FROZEN_AGENT_UUID or identity["name"] != FROZEN_AGENT_NAME:
        raise RuntimeError(
            f"authenticated identity mismatch: observed {identity['uuid']}/{identity['name']}, "
            f"expected {FROZEN_AGENT_UUID}/{FROZEN_AGENT_NAME}"
        )
    active_games = stats.get("active_games") if isinstance(stats, dict) else None
    if isinstance(active_games, bool) or not isinstance(active_games, (int, float)):
        raise RuntimeError("platform stats do not expose a numeric active_games preflight field")
    if int(active_games) != 0:
        raise RuntimeError(f"refusing launch with {int(active_games)} pre-existing active game(s)")
    identity["active_games"] = int(active_games)
    return identity


def launch_canary(
    *, output_dir: str | Path, repo: str | Path = ".", client_class: type[Any] | None = None,
    env: Mapping[str, str] | None = None, per_family_games: int = 100, concurrency: int = 3,
    poll_interval: float = 2.0, rehearsal: bool = False,
) -> dict[str, Any]:
    """Launch the exact bounded canary; tests inject an offline client in rehearsal mode."""

    if not rehearsal and (per_family_games != 100 or concurrency != 3):
        raise ValueError("the frozen canary requires 100 games/family and concurrency 3")
    environ = dict(os.environ if env is None else env)
    api_key = environ.get("GLEE_API_KEY")
    if not api_key:
        raise RuntimeError("GLEE_API_KEY is required")
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"output directory must be new and empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    config = build_configuration_manifest(
        repo, env=environ, families=FAMILIES, per_family_games=per_family_games,
        concurrency=concurrency, allow_dirty=rehearsal,
    )
    config_sha = _sha256(_canonical_bytes(config))
    started = _utc_now()
    batch_id = f"jordan-{FROZEN_CANDIDATE_COMMIT[:8]}-{config_sha[:12]}-{started.replace(':', '').replace('+00:00', 'Z')}"
    launch = {
        "schema": "glee.live.launch_manifest.v1",
        "batch_id": batch_id,
        "started_at": started,
        "configuration_sha256": config_sha,
        "configuration": config,
    }
    _write_json(out / "launch_manifest.json", launch)
    recorder = TelemetryRecorder(
        out / "telemetry.jsonl", batch_id=batch_id, configuration_sha256=config_sha,
        secret_values=(api_key, environ.get("GLEE_TELEMETRY_HMAC_KEY", "")),
    )
    recorder.append("batch_initialized")

    try:
        if client_class is None:
            from glee_sdk import GleeClient
            client_class = GleeClient
        Client = telemetry_client_class(client_class)
        client = Client(api_key=api_key, telemetry_recorder=recorder)
        initial_stats = client.stats()
        identity = _validate_identity(initial_stats)
        recorder.append("identity_verified", identity=identity, stats=_redact(initial_stats))

        base_strategy = build_strategy(FROZEN_AGENT_SPEC, observation_log=None)
        telemetry_strategy = TelemetryStrategy(base_strategy, recorder)
    except BaseException as exc:
        recorder.append("preflight_failure", error_type=type(exc).__name__, error=str(exc))
        recorder.append("batch_stopped", counters={}, completed={})
        reconcile_batch(out)
        raise

    original_handle = client._handle_game

    def handle(strategy: Any, game: dict[str, Any]) -> Any:
        client.register_context(game)
        return original_handle(strategy, game)

    client._handle_game = handle
    completed_by_family: Counter[str] = Counter()
    active_families = list(FAMILIES)
    failure: BaseException | None = None
    try:
        client._leave_queue_quietly()
        while active_families and any(completed_by_family[family] < per_family_games for family in FAMILIES):
            wave = [family for family in active_families if completed_by_family[family] < per_family_games]
            before_seen = set(client._seen_game_ids)
            for family in wave:
                client.queue(family)
                recorder.append("queue_requested", family=family)
            while True:
                pending = client.pending_games()
                if pending:
                    with ThreadPoolExecutor(max_workers=min(concurrency, len(pending))) as pool:
                        futures = [pool.submit(client._handle_game, telemetry_strategy, game) for game in pending]
                        for future in as_completed(futures):
                            future.result()
                new_seen = set(client._seen_game_ids) - before_seen
                stats = client.stats()
                active = int(stats.get("active_games") or 0) if isinstance(stats, dict) else 0
                if len(new_seen) >= len(wave) and active == 0:
                    client.backfill_terminal_results(sorted(new_seen))
                    unresolved = sorted(new_seen - set(client._terminal_game_ids))
                    if unresolved:
                        recorder.append("unresolved_terminal_stop", game_ids=unresolved)
                    break
                if len(new_seen) > len(wave):
                    recorder.append("cap_violation", expected=len(wave), observed=len(new_seen))
                    raise RuntimeError("strict wave game cap violated")
                time.sleep(poll_interval)
            completed_by_family = Counter(str(row.get("family")) for row in client.terminal_records)
            if set(new_seen) - set(client._terminal_game_ids):
                break
            stop = evaluate_stop_rules(
                client.terminal_records, client.counters, telemetry_strategy.fallbacks_by_family
            )
            recorder.append("stop_rules_evaluated", completed=dict(completed_by_family), result=stop)
            if stop["global_stop"]:
                break
            active_families = [family for family in active_families if family not in stop["paused_families"]]
    except BaseException as exc:  # preserve, reconcile, then re-raise
        failure = exc
        recorder.append("batch_crash", error_type=type(exc).__name__, error=str(exc))
    finally:
        try:
            client._leave_queue_quietly()
        except Exception as exc:  # noqa: BLE001
            recorder.append("queue_leave_failure", error_type=type(exc).__name__, error=str(exc))
        client.backfill_terminal_results()
        recorder.append("batch_stopped", counters=dict(client.counters), completed=dict(completed_by_family))
        report = reconcile_batch(out)
    if failure is not None:
        raise failure
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Attributable frozen-Jordan canary telemetry")
    sub = parser.add_subparsers(dest="command", required=True)
    launch = sub.add_parser("launch")
    launch.add_argument("--output-dir", required=True)
    launch.add_argument("--repo", default=".")
    launch.add_argument("--per-family-games", type=int, default=100)
    launch.add_argument("--concurrency", type=int, default=3)
    launch.add_argument("--poll-interval", type=float, default=2.0)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    if args.command == "launch":
        result = launch_canary(
            output_dir=args.output_dir, repo=args.repo, per_family_games=args.per_family_games,
            concurrency=args.concurrency, poll_interval=args.poll_interval,
        )
    else:
        result = reconcile_batch(args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
