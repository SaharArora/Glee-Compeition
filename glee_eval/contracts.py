"""Declarative contracts for every payload that crosses into the agent.

Twice now the same failure mode has produced confidently-wrong behaviour with no
error anywhere: a field present under a name we did not read.

* Offline, the persuasion belief update read the round quality from
  `item["quality"]`, which only synthetic transcripts set -- real ones carry it at
  `raw.round_quality`. The agent learned nothing, its posterior stayed pinned at
  the prior, and it declined all 66,480 real buyer decisions. Nothing raised.
* Live, the competition API names eleven things differently from our offline
  format (`u` for the low value, `alice_gain` for a share, `"high"` for a quality).
  Each would have degraded silently in the same way.

Both are the *shadowed-by-alias* case, and it is the one a type check misses: the
payload is well-formed, the field is simply somewhere else. So that case gets its
own violation kind and is always loud, because a missing field usually announces
itself downstream as a `None` while a shadowed one quietly supplies a default.

Two enforcement modes exist because the cost of raising differs by boundary:

* `STRICT` -- raise `SchemaViolation`. Correct for offline paths, where a loud
  failure is free and a wrong number silently poisons an analysis.
* `OBSERVE` -- log at ERROR, count, and carry on. Required on the live path,
  where raising would propagate into `GleeClient._handle_game`, which swallows it
  and submits no move -- a turn timeout scored at the 5th percentile. "Loud" there
  has to mean a logged error and a counter in the run summary, never an exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

logger = logging.getLogger("glee_eval.contracts")


class Mode(str, Enum):
    STRICT = "strict"
    OBSERVE = "observe"
    OFF = "off"


class Problem(str, Enum):
    MISSING = "missing"
    #: The fact is somewhere in the payload but the reader production code
    #: actually uses cannot find it. This is precisely the bug that has bitten us
    #: twice, and unlike a missing field it produces no downstream `None` to
    #: notice -- the caller just takes a default and carries on.
    UNREADABLE = "unreadable"
    #: Canonical key absent, alias populated, and no reader declared to resolve it.
    SHADOWED_BY_ALIAS = "shadowed_by_alias"
    WRONG_TYPE = "wrong_type"
    NULL = "null"
    EMPTY_PAYLOAD = "empty_payload"


class SchemaViolation(Exception):
    """Raised in STRICT mode when a payload does not satisfy its contract."""

    def __init__(self, contract: str, violations: Sequence["Violation"]):
        self.contract = contract
        self.violations = list(violations)
        super().__init__(f"{contract}: " + "; ".join(v.describe() for v in self.violations))


@dataclass(frozen=True)
class Violation:
    field: str
    problem: Problem
    detail: str = ""

    def describe(self) -> str:
        return f"{self.field} [{self.problem.value}]" + (f" -- {self.detail}" if self.detail else "")

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "problem": self.problem.value, "detail": self.detail}


@dataclass(frozen=True)
class Field:
    """One fact the agent needs, and every place that fact is known to live.

    `aliases` are not conveniences -- they are the trap. Listing them lets the
    validator distinguish "this data genuinely lacks a quality label" from "the
    quality is right there under a different key and we are about to ignore it".
    """

    name: str
    required: bool = True
    aliases: tuple[str, ...] = ()
    kind: type | tuple[type, ...] | None = None
    nullable: bool = False
    #: Nested containers to search for the canonical name and its aliases.
    containers: tuple[str, ...] = ("raw", "raw_record", "structured", "game_state", "configuration")
    #: The function production code actually uses to read this fact. When set, the
    #: check stops being "is the field where we expect" -- which real data often
    #: legitimately answers no -- and becomes "can the code we ship find it",
    #: which is the question that matters and the one that was silently failing.
    reader: Callable[[dict[str, Any]], Any] | None = None


@dataclass(frozen=True)
class Contract:
    name: str
    fields: tuple[Field, ...] = ()
    #: When set, the payload must be a non-empty mapping.
    require_mapping: bool = True


def _lookup(
    payload: dict[str, Any],
    key: str,
    containers: Iterable[str],
    *,
    require_value: bool = False,
) -> tuple[bool, Any, str]:
    """Find `key` at the top level or inside a known container.

    With `require_value`, a key whose value is null counts as absent. Real GLEE
    rows carry the full column set on every row, so a text-mode seller message has
    `raw.decision = null` -- the key is there, the fact is not. Treating that as
    "present" made the validator report 232,020 phantom violations, which is
    exactly the sort of noise that gets a checker ignored.
    """

    if key in payload and not (require_value and payload[key] is None):
        return True, payload[key], key
    for container in containers:
        nested = payload.get(container)
        if isinstance(nested, dict) and key in nested and not (require_value and nested[key] is None):
            return True, nested[key], f"{container}.{key}"
    return False, None, ""


def check(payload: Any, contract: Contract) -> list[Violation]:
    """Validate without raising. The building block both modes share."""

    if not isinstance(payload, dict) or (contract.require_mapping and not payload):
        return [Violation("<payload>", Problem.EMPTY_PAYLOAD, f"got {type(payload).__name__}")]

    violations: list[Violation] = []
    for spec in contract.fields:
        require_value = spec.reader is not None
        found, value, where = _lookup(payload, spec.name, spec.containers, require_value=require_value)
        alias_hits = [
            located
            for alias in spec.aliases
            for present, _, located in [_lookup(payload, alias, spec.containers, require_value=require_value)]
            if present
        ]

        if spec.reader is not None:
            # Judge the shipped reader, not the layout. Real payloads put facts in
            # several legitimate places; what must never happen is the fact being
            # present and the reader coming back empty.
            try:
                read = spec.reader(payload)
            except Exception as exc:  # noqa: BLE001 - a throwing reader is itself the defect
                violations.append(Violation(spec.name, Problem.UNREADABLE, f"reader raised {type(exc).__name__}: {exc}"))
                continue
            if read is None:
                located = [where] if found else []
                located += alias_hits
                if located:
                    violations.append(
                        Violation(
                            spec.name,
                            Problem.UNREADABLE,
                            f"present at {', '.join(located)} but the production reader returned None",
                        )
                    )
                elif spec.required:
                    violations.append(Violation(spec.name, Problem.MISSING, f"looked for {[spec.name, *spec.aliases]}"))
            continue

        if not found:
            if alias_hits:
                violations.append(
                    Violation(
                        spec.name,
                        Problem.SHADOWED_BY_ALIAS,
                        f"absent, but present as {', '.join(alias_hits)} -- reading the canonical "
                        f"name alone would silently see nothing",
                    )
                )
            elif spec.required:
                looked = [spec.name, *spec.aliases]
                violations.append(Violation(spec.name, Problem.MISSING, f"looked for {looked}"))
            continue

        if value is None and not spec.nullable:
            if spec.required:
                violations.append(Violation(spec.name, Problem.NULL, f"found at {where} but null"))
            continue
        if spec.kind is not None and value is not None and not isinstance(value, spec.kind):
            expected = spec.kind if isinstance(spec.kind, type) else spec.kind
            names = expected.__name__ if isinstance(expected, type) else "/".join(k.__name__ for k in expected)
            violations.append(
                Violation(spec.name, Problem.WRONG_TYPE, f"at {where}: expected {names}, got {type(value).__name__}")
            )
    return violations


@dataclass
class ContractReport:
    """Accumulates violations for boundaries that must not raise."""

    counts: dict[str, int] = dataclass_field(default_factory=dict)
    samples: list[dict[str, Any]] = dataclass_field(default_factory=list)
    max_samples: int = 25

    def record(self, contract: str, violations: Sequence[Violation]) -> None:
        for violation in violations:
            key = f"{contract}:{violation.field}:{violation.problem.value}"
            self.counts[key] = self.counts.get(key, 0) + 1
            if len(self.samples) < self.max_samples:
                self.samples.append({"contract": contract, **violation.to_dict()})

    @property
    def clean(self) -> bool:
        return not self.counts

    def to_dict(self) -> dict[str, Any]:
        return {"clean": self.clean, "violation_counts": dict(self.counts), "samples": list(self.samples)}


def enforce(
    payload: Any,
    contract: Contract,
    *,
    mode: Mode = Mode.STRICT,
    report: ContractReport | None = None,
    context: str = "",
) -> list[Violation]:
    """Validate `payload`, raising or logging according to `mode`."""

    if mode is Mode.OFF:
        return []
    violations = check(payload, contract)
    if not violations:
        return []
    if report is not None:
        report.record(contract.name, violations)
    label = f"{contract.name}{f' ({context})' if context else ''}"
    if mode is Mode.STRICT:
        raise SchemaViolation(label, violations)
    logger.error("Schema mismatch in %s: %s", label, "; ".join(v.describe() for v in violations))
    return violations


# ---------------------------------------------------------------------------
# The contracts themselves
# ---------------------------------------------------------------------------

#: A transcript row from an ingested real game. `quality` and `decision` are the
#: two that have actually bitten us; both live under `raw` in real data and at the
#: top level in synthetic data.
def _quality_reader(row: dict[str, Any]) -> Any:
    from glee_eval.data.transcripts import transcript_item_quality

    return transcript_item_quality(row)


def _decision_reader(row: dict[str, Any]) -> Any:
    from glee_eval.data.transcripts import transcript_item_decision

    return transcript_item_decision(row)


TRANSCRIPT_QUALITY_ROW = Contract(
    name="transcript.nature_quality",
    fields=(
        Field("action_type", kind=str),
        Field("round", kind=(int, float)),
        Field("quality", aliases=("round_quality",), reader=_quality_reader),
    ),
)

def _message_reader(row: dict[str, Any]) -> Any:
    from glee_eval.data.transcripts import as_dict

    raw = as_dict(row.get("raw") or row.get("raw_record"))
    value = row.get("free_text_message") or raw.get("message")
    return str(value) if value else None


TRANSCRIPT_MESSAGE_ROW = Contract(
    name="transcript.message",
    fields=(
        Field("action_type", kind=str),
        Field("round", kind=(int, float)),
        Field("free_text_message", aliases=("message",), reader=_message_reader),
    ),
)

TRANSCRIPT_DECISION_ROW = Contract(
    name="transcript.decision",
    fields=(
        Field("action_type", kind=str),
        Field("round", kind=(int, float)),
        Field("buy_no_buy", aliases=("decision", "recommendation"), reader=_decision_reader),
    ),
)

#: An ingested event, as produced by `data/ingest.py` and consumed by probes.
INGESTED_EVENT = Contract(
    name="ingest.event",
    fields=(
        Field("game_id"),
        Field("game_family", kind=str),
        Field("role", kind=str),
        Field("round", kind=(int, float)),
        Field("action_type", kind=str),
        Field("configuration", aliases=("public_parameters", "game_args"), kind=dict),
    ),
)

_LIVE_COMMON = (
    Field("game_id"),
    Field("game_family", kind=str),
    Field("valid_actions", kind=dict),
    Field("game_state", kind=dict),
)

#: Live payloads. Aliases here are our *offline* names -- if the server ever sends
#: `self_gain` or `c`, that is exactly as wrong as the reverse and should be loud.
LIVE_BARGAINING = Contract(
    name="live.bargaining",
    fields=(
        *_LIVE_COMMON,
        Field("money_to_divide", aliases=("money",), kind=(int, float)),
        Field("current_player", aliases=("your_player",), kind=str),
        Field("round", kind=(int, float)),
        Field("horizon_known", required=False, kind=bool),
        Field("max_rounds", required=False, kind=(int, float)),
        Field("last_offer", required=False, nullable=True, kind=dict),
        Field("history", kind=list),
    ),
)

LIVE_NEGOTIATION = Contract(
    name="live.negotiation",
    fields=(
        *_LIVE_COMMON,
        Field("current_player", aliases=("your_player",), kind=str),
        Field("round", kind=(int, float)),
        Field("player_1_role", aliases=("role", "seller_role"), kind=str),
        Field("player_2_role", aliases=("role", "buyer_role"), kind=str),
        Field("last_offer", required=False, nullable=True, kind=dict),
        Field("history", kind=list),
    ),
)

def _live_persuasion_high_reader(row: dict[str, Any]) -> Any:
    from glee_eval.live.schema import persuasion_unit_values

    return persuasion_unit_values(row)[0]


def _live_persuasion_low_reader(row: dict[str, Any]) -> Any:
    from glee_eval.live.schema import persuasion_unit_values

    return persuasion_unit_values(row)[1]


LIVE_PERSUASION = Contract(
    name="live.persuasion",
    fields=(
        *_LIVE_COMMON,
        Field("product_price", kind=(int, float)),
        Field("p", kind=(int, float)),
        Field("round", kind=(int, float)),
        Field("total_rounds", aliases=("max_rounds",), kind=(int, float)),
        Field("current_player", aliases=("your_player",), kind=str),
        Field("history", kind=list),
        # `u` is the live name for what we call `c`. Listing `c` as the alias means
        # a server that switched to our spelling would be caught, not absorbed.
        #
        # Required, and judged on the shipped reader. These were `required=False`,
        # which made the contract silent about the one persuasion failure it most
        # needed to catch: `_persuasion_state` guards both with `is not None`, so a
        # missing or renamed value field does not raise -- it quietly omits `v`/`c`
        # from the config and the agent prices the whole game off defaults. That is
        # a buyer with no idea what a unit is worth, and it looks like clean data.
        # No `kind`: it is not checked once a reader is set, and declaring one would
        # imply a type check that never runs. The reader coerces, so a numeric string
        # is genuinely harmless here -- what matters is that it comes back non-None.
        Field("u", aliases=("c", "low_value"), reader=_live_persuasion_low_reader),
        Field("v", aliases=("high_value",), reader=_live_persuasion_high_reader),
    ),
)

LIVE_CONTRACTS = {
    "bargaining": LIVE_BARGAINING,
    "negotiation": LIVE_NEGOTIATION,
    "persuasion": LIVE_PERSUASION,
}


def live_contract(game_family: str) -> Contract | None:
    return LIVE_CONTRACTS.get(str(game_family or ""))
