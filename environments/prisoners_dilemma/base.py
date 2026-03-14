"""Base multi-agent environment."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass
class Interaction:
    """A single unit of environment progression (round, task, turn)."""
    id: str
    context: Dict[str, Any]
    ground_truth: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentConfig:
    """Configuration for multi-agent environments."""
    max_interactions: int = 100
    max_turns_per_interaction: int = 5
    agent_roles: Sequence[str] = field(default_factory=tuple)
    seed: Optional[int] = None
    initial_recruiters: Sequence[str] = field(default_factory=tuple)
    initial_honest_agents: Sequence[str] = field(default_factory=tuple)
    env_params: Dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **overrides) -> "EnvironmentConfig":
        return replace(self, **overrides)


class MultiAgentEnvironment(abc.ABC):
    """
    Abstract base class for multi-agent environments.
    
    Subclasses must increment interaction_count in step() to enable
    should_terminate() to work correctly.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        self.config = config
        self.current_interaction: Optional[Interaction] = None
        self.interaction_count = 0
        self.turn_count = 0
        self.global_transcript: List[Dict[str, Any]] = []
        self.metrics = self._initialize_metrics()
        self._done = False
        self.messages = {}

    @abc.abstractmethod
    def _initialize_metrics(self) -> Any:
        """Return an initialised metrics tracker for this environment."""
        ...

    @abc.abstractmethod
    def _generate_next_interaction(self) -> Optional[Interaction]:
        """Generate next interaction, or None to stop."""
        ...

    @abc.abstractmethod
    def _get_observation(self, interaction: Interaction, agent_id: str) -> Dict[str, Any]:
        """Build agent-specific observation for current interaction."""
        ...

    @abc.abstractmethod
    def step(
        self,
        agent_actions: Mapping[str, Any]
    ) -> Tuple[Mapping[str, Dict[str, Any]], Dict[str, float], bool, Dict[str, Any]]:
        """Process actions, return (observations, rewards, done, info)."""
        ...

    @abc.abstractmethod
    def reset(self, seed: Optional[int] = None) -> Mapping[str, Dict[str, Any]]:
        """Reset environment, return initial observations."""
        ...


    def should_terminate(self) -> bool:
        """Whether the episode should end. Override for custom logic."""
        return self.interaction_count >= self.config.max_interactions

    def log_to_transcript(self, entry: Dict[str, Any]) -> None:
        """Append an entry to the global transcript."""
        self.global_transcript.append(entry)