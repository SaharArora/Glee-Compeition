from __future__ import annotations

from abc import ABC, abstractmethod

from glee_eval.data.schemas import AgentAction, GameState, OpponentSpec


class OpponentPolicy(ABC):
    def __init__(self, spec: OpponentSpec):
        self.spec = spec

    @abstractmethod
    def decide(self, state: GameState) -> AgentAction:
        raise NotImplementedError

