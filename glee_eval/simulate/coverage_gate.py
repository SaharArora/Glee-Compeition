from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glee_eval.data.dataset_audit import context_support_lookup, support_lookup
from glee_eval.storage.trajectories import read_json


DEFAULT_COVERAGE_THRESHOLD = 0.35
DEFAULT_MAX_DISPATCHES = 3


@dataclass(frozen=True)
class CoverageVerdict:
    """One reading of the audit support index for a single decision."""

    family: str
    role: str
    action_type: str
    coverage_score: float
    inside_support: bool
    threshold: float
    known: bool
    n: int
    action_n: int
    density: float
    action_bin: str
    bucket_key: str | None
    bucket_level: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "role": self.role,
            "action_type": self.action_type,
            "coverage_score": self.coverage_score,
            "inside_support": self.inside_support,
            "threshold": self.threshold,
            "known": self.known,
            "n": self.n,
            "action_n": self.action_n,
            "density": self.density,
            "action_bin": self.action_bin,
            "bucket_key": self.bucket_key,
            "bucket_level": self.bucket_level,
        }


class CoverageGate:
    """Single shared currency for "how much real data do we have here?".

    Measurement before action, in two steps:

    1. `context_coverage` / `evaluate` only *read* the audit support index. They
       are cheap, side-effect free apart from recording, and safe to call on
       every decision.
    2. `request_counterfactual` is the only method that can cause simulation. It
       fires the dispatcher's `counterfactual` trigger for a decision that fell
       outside empirical support, and refuses to fire when the request is a
       repeat of a bucket already probed, when the per-run budget is spent, or
       when no dispatcher is attached.

    Every request is recorded with its outcome, including the ones that were
    deduplicated or dropped for budget, so a run never silently under-covers.
    """

    def __init__(
        self,
        support_index: dict[str, Any] | None = None,
        *,
        threshold: float = DEFAULT_COVERAGE_THRESHOLD,
        dispatcher: Any = None,
        max_dispatches: int = DEFAULT_MAX_DISPATCHES,
        games_per_dispatch: int = 25,
        output_root: str | Path = "reports/counterfactual_simulation",
    ):
        self.support_index = support_index or {"buckets": {}}
        self.threshold = threshold
        self.dispatcher = dispatcher
        self.max_dispatches = max_dispatches
        self.games_per_dispatch = games_per_dispatch
        self.output_root = Path(output_root)
        self.verdicts: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self._probed: set[tuple[str, str, str, str]] = set()
        self._dispatch_count = 0

    @classmethod
    def from_path(cls, path: str | Path | None, **kwargs: Any) -> "CoverageGate | None":
        """Build a measurement-only gate from a `support_index.json` path."""

        if not path:
            return None
        p = Path(path)
        if p.is_dir():
            p = p / "support_index.json"
        if not p.exists():
            return None
        return cls(read_json(p), **kwargs)

    @property
    def has_index(self) -> bool:
        return bool(self.support_index.get("buckets"))

    @property
    def dispatches_remaining(self) -> int:
        return max(0, self.max_dispatches - self._dispatch_count)

    # ------------------------------------------------------------------
    # Reading the index
    # ------------------------------------------------------------------
    def context_coverage(
        self,
        family: str,
        config: dict[str, Any],
        role: str,
        action_type: str,
        state: Any = None,
    ) -> dict[str, Any]:
        """Support for the situation, before a candidate action exists.

        Returns `found: False` both when no index is loaded and when the index
        has nothing for this context; callers must consult `has_index` to tell
        "we have no data source" from "our data source says this is a gap".
        """

        if not self.has_index:
            return {"n": 0, "density": 0.0, "context_score": 0.0, "bucket_key": None, "bucket_level": None, "found": False}
        return context_support_lookup(family, config, role, action_type, state, support_index=self.support_index)

    def evaluate(
        self,
        family: str,
        config: dict[str, Any],
        role: str,
        action: Any,
        state: Any = None,
        *,
        record: bool = True,
    ) -> CoverageVerdict:
        """Action-level support for a decision the agent is about to commit to."""

        support = support_lookup(family, config, role, action, state, support_index=self.support_index)
        known = self.has_index and support.get("bucket_level") not in {None, "unknown"}
        coverage = float(support.get("coverage_score") or 0.0)
        verdict = CoverageVerdict(
            family=family,
            role=role,
            action_type=self._action_type(action),
            coverage_score=coverage,
            # An unknown index cannot indict an action: treat it as inside support
            # so a data-less run stays on the rule-based path instead of flipping
            # every decision into "out of distribution".
            inside_support=(not known) or coverage >= self.threshold,
            threshold=self.threshold,
            known=known,
            n=int(support.get("n") or 0),
            action_n=int(support.get("action_n") or 0),
            density=float(support.get("density") or 0.0),
            action_bin=str(support.get("action_bin") or "unknown"),
            bucket_key=support.get("bucket_key"),
            bucket_level=support.get("bucket_level"),
        )
        if record:
            self.verdicts.append(verdict.to_dict())
        return verdict

    # ------------------------------------------------------------------
    # Acting on the index
    # ------------------------------------------------------------------
    def request_counterfactual(
        self,
        family: str,
        config: dict[str, Any],
        role: str,
        action: Any,
        state: Any = None,
        *,
        verdict: CoverageVerdict | None = None,
    ) -> dict[str, Any]:
        """Ask for a targeted counterfactual simulation of an out-of-support action."""

        verdict = verdict or self.evaluate(family, config, role, action, state, record=False)
        request: dict[str, Any] = {"coverage": verdict.to_dict()}
        if verdict.inside_support:
            request["status"] = "inside_support"
        elif self.dispatcher is None:
            request["status"] = "no_dispatcher"
        else:
            probe_key = (family, role, verdict.action_type, verdict.action_bin)
            if probe_key in self._probed:
                request["status"] = "duplicate_bucket"
            elif self.dispatches_remaining <= 0:
                request["status"] = "budget_exhausted"
                request["max_dispatches"] = self.max_dispatches
            else:
                self._probed.add(probe_key)
                self._dispatch_count += 1
                request["status"] = "dispatched"
                request["dispatch_index"] = self._dispatch_count
                result = self.dispatcher.counterfactual_simulation(
                    family=family,
                    config=config,
                    role=role,
                    action=action,
                    state=state,
                    threshold=self.threshold,
                    games=self.games_per_dispatch,
                    output_dir=self.output_root / f"{family}_{verdict.action_type}_{self._dispatch_count}",
                )
                request["skipped_by_dispatcher"] = bool(result.get("skipped"))
                request["output_dir"] = result.get("output_dir")
        self.requests.append(request)
        return request

    # ------------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for request in self.requests:
            status = str(request.get("status"))
            statuses[status] = statuses.get(status, 0) + 1
        scored = [v for v in self.verdicts if v.get("known")]
        return {
            "has_index": self.has_index,
            "threshold": self.threshold,
            "decisions_evaluated": len(self.verdicts),
            "decisions_with_known_support": len(scored),
            "out_of_support_decisions": sum(1 for v in scored if not v.get("inside_support")),
            "mean_coverage_score": (sum(float(v["coverage_score"]) for v in scored) / len(scored)) if scored else None,
            "counterfactual_requests": len(self.requests),
            "request_status_counts": statuses,
            "dispatch_budget": self.max_dispatches,
            "dispatches_used": self._dispatch_count,
        }

    @staticmethod
    def _action_type(action: Any) -> str:
        if isinstance(action, dict):
            return str(action.get("action_type") or "unknown")
        return str(getattr(action, "action_type", None) or "unknown")
