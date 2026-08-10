from __future__ import annotations

from glee_eval.data.schemas import EpisodeResult, FailureDiagnostic, FailureType, to_jsonable


def diagnose_episode(episode: EpisodeResult) -> list[FailureDiagnostic]:
    failures: list[FailureDiagnostic] = []
    metrics = episode.metrics
    failure_type = None
    notes = ""
    if metrics.get("malformed_response", 0) > 0:
        failure_type = FailureType.FORMAT_FAILURE.value
        notes = "At least one response could not be parsed."
    elif metrics.get("illegal_action", 0) > 0:
        failure_type = FailureType.ILLEGAL_ACTION.value
        notes = "At least one action violated the local action constraints."
    elif metrics.get("ir_violation", 0) > 0:
        failure_type = FailureType.IR_VIOLATION.value
        notes = "Candidate accepted or proposed a dominated trade under the local payoff model."
    elif episode.candidate_payoff < metrics.get("reference_payoff", 0):
        regret = metrics.get("reference_payoff", 0) - episode.candidate_payoff
        if regret > 0.25:
            failure_type = FailureType.OVER_AGGRESSIVE.value if metrics.get("trade_or_sale") is False else FailureType.UNDER_AGGRESSIVE.value
            notes = "Candidate payoff is substantially below the simple reference payoff."
    if failure_type:
        failures.append(
            FailureDiagnostic(
                failure_type=failure_type,
                scenario=to_jsonable(episode.scenario),
                transcript=episode.full_transcript,
                candidate_actions=[to_jsonable(record.action) for record in episode.decision_records if record.role == episode.scenario.candidate_role],
                opponent_behavior=[to_jsonable(record.action) for record in episode.decision_records if record.role != episode.scenario.candidate_role],
                candidate_payoff=episode.candidate_payoff,
                reference_payoff=metrics.get("reference_payoff"),
                regret=metrics.get("regret"),
                critical_round=metrics.get("critical_round"),
                confidence=0.6,
                notes=notes,
            )
        )
    return failures

