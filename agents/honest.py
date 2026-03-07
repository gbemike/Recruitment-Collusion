"""Aligned agent implementations."""

from __future__ import annotations

from typing import Mapping, Any
from .base import AgentContext, BaseAgent

class HonestAgent(BaseAgent):
    """
    Baseline agent that focuses on task accuracy and objective performance.
    """

    def __init__(self, context: AgentContext) -> None:
        super().__init__(context)

    def act(self, observation: Mapping[str, Any]) -> str:
        """
        Placeholder for the acting logic..
        """
        raise NotImplementedError("Action logic is handled by LLMHonestAgent")