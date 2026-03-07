"""Agent interface definitions for ColludeBench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass
class AgentContext:
    """Context provided to policies each round."""

    role: str  # agents behaviour at each round (required)
    recruiter: bool
    agent_id: str | None = None
    blueprint_role: str | None = None  # agents consistent behaviour
    run_seed: int | None = None
    payload_rate: float | None = None


class BaseAgent:
    """Abstract base class providing shared utilities for agents."""

    def __init__(self, context: AgentContext) -> None:
        self.context = context

    def act(self, observation: Mapping[str, Any]) -> str:  # pragma: no cover - interface
        raise NotImplementedError