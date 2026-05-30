"""Recruiter agent base class."""

from __future__ import annotations

from typing import Mapping, Any
from .base import AgentContext, BaseAgent


class RecruiterAgent(BaseAgent):
	"""
	Scaffold for a Recruiter
	"""

	def __init__(self, context: AgentContext) -> None:
		super().__init__(context)

	def act(self, observation: Mapping[str, Any]) -> str:
		"""Implemented by LLMRecruiterAgent."""
		raise NotImplementedError('Action logic is handled by LLMRecruiterAgent in llm.py')
