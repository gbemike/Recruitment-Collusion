"""Task-centric routing environment for social contagion."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Iterable, Protocol


@dataclass
class Task:
    """Represents a specific unit of work with a known Ground Truth."""
    id: str
    content: str
    ground_truth: Any
    assigned_to: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "OPEN"  # OPEN, RESOLVED, EXPIRED
    interaction_count: int = 0


@dataclass(frozen=True)
class EnvironmentConfig:
    """Configuration for routing-based contagion environments."""
    max_total_turns: int = 50 
    max_interactions_per_task: int = 5
    agent_roles: Sequence[str] = field(default_factory=list)
    initial_recruiters: Sequence[str] = field(default_factory=tuple)
    initial_honest_agents: Sequence[str] = field(default_factory=tuple)
    routing_permissions: Mapping[str, Sequence[str]] = field(default_factory=dict)
    seed: Optional[int] = None
    
    def with_updates(self, **overrides) -> "EnvironmentConfig":
        return replace(self, **overrides)


class MultiAgentEnvironment(abc.ABC):
    """
    Skeleton class for Observer Environments
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        self.config = config
        self.current_turn = 0
        self.tasks: List[Task] = []
        self.active_task_index: int = 0
        self.transcript: List[Dict[str, Any]] = []
        
        # Metrics tracking: Purpose is to measure 'Drift' and 'Contagion'
        self.metrics = {
            "task_accuracy": [],      # [bool, bool, ...]
            "contagion_events": 0,    # Integer count
            "interaction_density": [] # [int, int, ...]
        }

    @abc.abstractmethod
    def setup_scenario(self):
        """Define tasks and Ground Truths."""

    @abc.abstractmethod
    def reset(self, seed: Optional[int] = None) -> Mapping[str, Mapping[str, Any]]:
        """Initialize state and return initial observations."""

    @abc.abstractmethod
    def _get_observation(self, task: Task) -> Dict[str, Any]:
        """Construct context for an agent based on task state."""

    @abc.abstractmethod
    def step(self, agent_responses: Mapping[str, str]) -> Tuple[Mapping[str, Mapping[str, Any]], Dict[str, float], bool, Dict[str, Any]]:
        """Process agent responses and transition to next state."""

    @abc.abstractmethod
    def _evaluate_performance(self, task: Task, action: Any):
        """Compare agent action to ground truth."""

    @abc.abstractmethod
    def is_task_complete(self, task: Task, last_response: Dict[str, Any]) -> bool:
        """Determine if a task should be closed."""

    def render_transcript(self) -> List[Dict[str, Any]]:
        """Default utility to export task history."""
        return [{"task_id": t.id, "history": t.history} for t in self.tasks]


class TranscriptLogger(Protocol):
    """Logging interface for recording interactions."""
    def log_turn(self, *, run_id: str, round_id: int, agent_id: str, role: str, response_dat: Mapping[str, Any], metrics: Dict[str, Any]) -> None:
        ...
    def flush(self) -> None:
        ...


def agent_order(agent_roles: Sequence[str]) -> Iterable[str]:
    """Provide deterministic agent ordering for transcripts."""
    return agent_roles