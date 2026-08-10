from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Mapping


class GameFamily(str, Enum):
    BARGAINING = "bargaining"
    NEGOTIATION = "negotiation"
    PERSUASION = "persuasion"


class FailureType(str, Enum):
    FORMAT_FAILURE = "FORMAT_FAILURE"
    ILLEGAL_ACTION = "ILLEGAL_ACTION"
    IR_VIOLATION = "IR_VIOLATION"
    OVER_AGGRESSIVE = "OVER_AGGRESSIVE"
    UNDER_AGGRESSIVE = "UNDER_AGGRESSIVE"
    EXCESSIVE_DELAY = "EXCESSIVE_DELAY"
    BAD_COMMITMENT = "BAD_COMMITMENT"
    BAD_BELIEF_UPDATE = "BAD_BELIEF_UPDATE"
    OPPONENT_MISCLASSIFICATION = "OPPONENT_MISCLASSIFICATION"
    REPUTATION_FAILURE = "REPUTATION_FAILURE"
    LANGUAGE_ACTION_CONTRADICTION = "LANGUAGE_ACTION_CONTRADICTION"
    UNKNOWN = "UNKNOWN"


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    game_family: str
    config_id: str
    public_parameters: JsonDict
    candidate_role: str
    opponent_role: str
    opponent_spec: JsonDict
    seed: int
    source: str = "synthetic"
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class GameState:
    scenario_id: str
    game_id: str
    game_family: str
    role: str
    round: int
    horizon: int
    public_parameters: JsonDict
    private_parameters: JsonDict
    visible_transcript: list[JsonDict]
    valid_action_schema: JsonDict
    termination_status: str = "ongoing"
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentAction:
    action_id: str
    actor_role: str
    round: int
    raw_text: str
    action_type: str
    numeric_action: float | None = None
    message: str | None = None
    accept_reject: str | None = None
    buy_no_buy: str | None = None
    is_parseable: bool = True
    is_legal: bool = True
    parse_errors: list[str] = field(default_factory=list)
    structured: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class OpponentSpec:
    archetype: str
    game_family: str
    parameters: JsonDict
    seed: int
    version: str = "0.1"
    description: str = ""


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    game_id: str
    scenario_id: str
    source: str
    game_family: str
    config_id: str
    role: str
    round: int
    visible_state: JsonDict
    action: JsonDict
    historical_action: JsonDict | None = None
    reference_action: JsonDict | None = None
    terminal_result: JsonDict | None = None
    player_payoff: float | None = None
    opponent_payoff: float | None = None
    estimated_regret: float | None = None
    checks: JsonDict = field(default_factory=dict)
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class FailureDiagnostic:
    failure_type: str
    scenario: JsonDict
    transcript: list[JsonDict]
    candidate_actions: list[JsonDict]
    opponent_behavior: list[JsonDict]
    candidate_payoff: float
    reference_payoff: float | None = None
    regret: float | None = None
    critical_round: int | None = None
    confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    scenario: Scenario
    candidate_agent_id: str
    opponent_spec: OpponentSpec
    full_transcript: list[JsonDict]
    decision_records: list[DecisionRecord]
    terminal_outcome: JsonDict
    candidate_payoff: float
    opponent_payoff: float
    metrics: JsonDict
    failure_diagnostics: list[FailureDiagnostic] = field(default_factory=list)
    replay_artifacts: JsonDict = field(default_factory=dict)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def compact_id(*parts: object) -> str:
    return "-".join(str(p).replace("/", "_").replace(" ", "_") for p in parts if p is not None)

