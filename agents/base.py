"""Agent interface definitions for ColludeBench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass
class AgentContext:
	"""Context provided to policies each round."""

	agent_id: str | None = None
	role: str  # agents behaviour at each round (required)
	recruiter: bool


class BaseAgent:
	"""Abstract base class providing shared utilities for agents."""

	def __init__(self, context: AgentContext) -> None:
		self.context = context

	def act(self, observation: Mapping[str, Any]) -> str:
		raise NotImplementedError
