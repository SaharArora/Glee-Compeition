"""Isolated, default-off negotiation candidates for validated Model-B gates."""

from __future__ import annotations

from typing import Any

from my_agents.jordan_strategic import JordanStrategicAgent


_FLAGS = (
    "use_time_concession",
    "guarantee_own_margin",
    "debias_counterpart_value",
    "use_unknown_horizon_counter_fallback",
    "use_unknown_horizon_counter_preservation",
)


class _IsolatedModelBCandidate(JordanStrategicAgent):
    enabled_flag: str

    def __init__(self, seed: int = 0, **kwargs: Any):
        for flag in _FLAGS:
            kwargs.pop(flag, None)
        settings = {flag: flag == self.enabled_flag for flag in _FLAGS}
        super().__init__(seed=seed, **settings, **kwargs)


class TimeConcessionModelBCandidate(_IsolatedModelBCandidate):
    enabled_flag = "use_time_concession"


class GuaranteeOwnMarginModelBCandidate(_IsolatedModelBCandidate):
    enabled_flag = "guarantee_own_margin"


class DebiasCounterpartValueModelBCandidate(_IsolatedModelBCandidate):
    enabled_flag = "debias_counterpart_value"


class UnknownHorizonCounterPreservationModelBCandidate(_IsolatedModelBCandidate):
    enabled_flag = "use_unknown_horizon_counter_preservation"
