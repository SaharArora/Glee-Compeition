"""Treatment-blind intent-to-treat handling for controlled-receiver failures.

The rule is frozen before capability or factorial outcomes.  It never drops or
replaces an assigned row.  A failed buyer decision is converted to the legal
``pass``/``no`` action for that round, after which the ordinary persuasion
environment continues to its fixed horizon and computes the numeric terminal
payoff.  This is an execution rule, not post-outcome payoff imputation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


ITT_RULE_SCHEMA = "glee.research.receiver_failure_itt.v1"
ITT_RESOLUTION_SCHEMA = "glee.research.receiver_failure_itt_resolution.v1"
FAILURE_KINDS = ("timeout", "malformed", "refusal", "missing", "exhausted_retry")
RETRYABLE_FAILURES = frozenset({"timeout", "malformed"})
RECEIVER_FAILURE_ITT_RULE: dict[str, Any] = {
    "schema": ITT_RULE_SCHEMA,
    "population": "every_assigned_persuasion_candidate_seller_receiver_round",
    "treatment_blind": True,
    "decision_mapping": {
        "ok_buy": {"controlled_decision": "buy", "environment_action": "yes"},
        "ok_pass": {"controlled_decision": "pass", "environment_action": "no"},
        **{
            status: {"controlled_decision": "pass", "environment_action": "no"}
            for status in FAILURE_KINDS
        },
    },
    "retry_rule": {
        "timeout": "one_retry_then_exhausted_retry",
        "malformed": "one_retry_then_exhausted_retry",
        "refusal": "no_retry",
        "missing": "no_retry",
        "maximum_attempts": 2,
        "arm_specific_retry_forbidden": True,
    },
    "continuation": (
        "append the mapped legal buyer action for the current round and continue the ordinary "
        "fixed-horizon persuasion environment with the preassigned nature stream"
    ),
    "numeric_payoff": (
        "use the ordinary environment terminal candidate payoff after all mapped actions; "
        "for persuasion this is the finite role payoff normalized by product_price*total_rounds"
    ),
    "row_exclusion": "forbidden",
    "row_replacement": "forbidden",
    "automatic_provider_fallback": "forbidden",
    "engine_failure": "global_stop_nonreportable_not_receiver_imputation",
}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


RECEIVER_FAILURE_ITT_RULE_SHA256 = canonical_hash(RECEIVER_FAILURE_ITT_RULE)


@dataclass(frozen=True)
class ReceiverITTResolution:
    observed_status: str
    effective_status: str
    attempts: int
    controlled_decision: str
    environment_action: str
    used_failure_rule: bool
    rule_sha256: str = RECEIVER_FAILURE_ITT_RULE_SHA256

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ITT_RESOLUTION_SCHEMA,
            "observed_status": self.observed_status,
            "effective_status": self.effective_status,
            "attempts": self.attempts,
            "controlled_decision": self.controlled_decision,
            "environment_action": self.environment_action,
            "used_failure_rule": self.used_failure_rule,
            "rule_sha256": self.rule_sha256,
        }


def resolve_receiver_itt(
    *, status: str, decision: str | None, failure_kind: str | None, attempts: int
) -> ReceiverITTResolution:
    """Map one final receiver observation to a legal environment action."""

    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 2:
        raise ValueError("receiver attempts must be one or two")
    if status == "ok":
        if failure_kind is not None or decision not in {"buy", "pass"}:
            raise ValueError("successful receiver observation is malformed")
        return ReceiverITTResolution(
            observed_status="ok",
            effective_status=f"ok_{decision}",
            attempts=attempts,
            controlled_decision=str(decision),
            environment_action="yes" if decision == "buy" else "no",
            used_failure_rule=False,
        )
    if status != "failure" or decision is not None or failure_kind not in FAILURE_KINDS:
        raise ValueError("failed receiver observation is malformed")
    effective = str(failure_kind)
    if failure_kind in RETRYABLE_FAILURES:
        if attempts != 2:
            raise ValueError("retryable receiver failures are final only after two attempts")
        effective = "exhausted_retry"
    elif failure_kind == "exhausted_retry":
        if attempts != 2:
            raise ValueError("exhausted_retry requires exactly two attempts")
    elif attempts != 1:
        raise ValueError("nonretryable receiver failures require exactly one attempt")
    return ReceiverITTResolution(
        observed_status="failure",
        effective_status=effective,
        attempts=attempts,
        controlled_decision="pass",
        environment_action="no",
        used_failure_rule=True,
    )


def bind_terminal_itt_payoff(
    resolution: ReceiverITTResolution, terminal_candidate_payoff: float
) -> dict[str, Any]:
    """Bind a finite natural terminal payoff to the pre-outcome ITT action rule."""

    payoff = float(terminal_candidate_payoff)
    if not math.isfinite(payoff):
        raise ValueError("receiver ITT requires a finite environment terminal payoff")
    return {
        "schema": "glee.research.receiver_failure_itt_payoff.v1",
        "resolution": resolution.to_dict(),
        "terminal_candidate_payoff": payoff,
        "payoff_source": "ordinary_environment_terminal_after_deterministic_itt_continuation",
        "numeric_payoff_available": True,
        "row_included_in_intent_to_treat": True,
    }


def validate_itt_rule(value: Mapping[str, Any]) -> None:
    if dict(value) != RECEIVER_FAILURE_ITT_RULE:
        raise ValueError("receiver-failure ITT rule differs from the frozen treatment-blind rule")


__all__ = [
    "RECEIVER_FAILURE_ITT_RULE",
    "RECEIVER_FAILURE_ITT_RULE_SHA256",
    "ReceiverITTResolution",
    "bind_terminal_itt_payoff",
    "resolve_receiver_itt",
    "validate_itt_rule",
]
