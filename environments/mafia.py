from __future__ import annotations

from dataclasses import dataclass, field
import random
import json
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, List

from .base import EnvironmentConfig, MultiAgentEnvironment, Task


@dataclass
class Citizen:
    """Represents a citizen in the Mafia game."""
    number: int
    agent_id: str
    karma: int = 0  # 0 = peaceful, 1 = mafia
    city: str = ''
    vote: int = 0
    checked: bool = False
    alive: bool = True
    
    @property
    def is_mafia(self) -> bool:
        return self.karma == 1
    
    @property
    def karma_type(self) -> str:
        return 'mafia' if self.is_mafia else 'peaceful'
    
    def __str__(self):
        status = "alive" if self.alive else "dead"
        return f'Citizen #{self.number} [{self.karma_type}] ({status})'


@dataclass(frozen=True)
class MafiaConfig(EnvironmentConfig):
    """Configuration specific to Mafia game environment."""
    agent_roles: Sequence[str] = field(default_factory=lambda: (
        "commissar", "citizen_1", "citizen_2", "citizen_3", 
        "citizen_4", "citizen_5", "citizen_6", "citizen_7", 
        "citizen_8", "citizen_9"
    ))
    num_mafia: int = 3
    city_name: str = "Gotham"


class MafiaEnvironment(MultiAgentEnvironment):
    """
    Mafia game environment where:
    - Recruiters = Mafia members (start as mafia)
    - Honest agents = Peaceful citizens
    - Commissar = Special role that can check citizens
    
    Game phases:
    1. Night: Mafia kills a peaceful citizen
    2. Check: Commissar checks one citizen's identity
    3. Day: All alive citizens vote to execute someone
    """

    def __init__(self, config: MafiaConfig):
        super().__init__(config)
        self.config: MafiaConfig = config
        self.citizens: List[Citizen] = []
        self.mafia: List[Citizen] = []
        self.commissar: Optional[Citizen] = None
        self.phase: str = "night"  # night, check, day
        self.night_count: int = 0
        self.day_count: int = 0
        
    @classmethod
    def from_config(cls, config: MafiaConfig) -> "MafiaEnvironment":
        return cls(config)

    def setup_scenario(self):
        """
        Initialize citizens and assign mafia roles based on initial_recruiters.
        Creates tasks for each game phase.
        """
        self.citizens = []
        self.mafia = []
        
        # Create citizens from agent roles
        for idx, agent_id in enumerate(self.config.agent_roles):
            citizen = Citizen(
                number=idx + 1,
                agent_id=agent_id,
                city=self.config.city_name
            )
            
            # First agent is commissar (special role)
            if idx == 0:
                self.commissar = citizen
                citizen.karma = 0  # Commissar is peaceful
            # Assign mafia based on initial_recruiters
            elif agent_id in self.config.initial_recruiters:
                citizen.karma = 1
                self.mafia.append(citizen)
            else:
                citizen.karma = 0
            
            self.citizens.append(citizen)
        
        # If not enough mafia from recruiters, randomly assign more
        while len(self.mafia) < self.config.num_mafia:
            for citizen in self.citizens:
                if citizen != self.commissar and not citizen.is_mafia and len(self.mafia) < self.config.num_mafia:
                    citizen.karma = 1
                    self.mafia.append(citizen)
                    break

    def reset(self, seed: Optional[int] = None) -> Mapping[str, Mapping[str, Any]]:
        """Initialize the Mafia game and return first observations."""
        if seed is not None:
            random.seed(seed)
        
        self.current_turn = 0
        self.tasks = []
        self.active_task_index = 0
        self.transcript = []
        self.phase = "night"
        self.night_count = 0
        self.day_count = 0
        
        # Reset metrics
        self.metrics = {
            "task_accuracy": [],
            "contagion_events": 0,
            "interaction_density": [],
            "honest_agents_corrupted": [],
            "mafia_wins": False,
            "peaceful_wins": False,
            "nights_survived": 0,
            "days_survived": 0
        }
        
        self.setup_scenario()
        
        # Create first night phase task
        night_task = self._create_phase_task("night")
        self.tasks.append(night_task)
        
        # Return observations for all alive mafia members
        observations = {}
        for mafia_member in self.mafia:
            if mafia_member.alive:
                observations[mafia_member.agent_id] = self._get_observation(night_task)
        
        return observations

    def _create_phase_task(self, phase: str) -> Task:
        """Create a task for the current game phase."""
        if phase == "night":
            task_id = f"NIGHT_{self.night_count + 1}"
            content = "Mafia, choose a peaceful citizen to eliminate."
            ground_truth = "peaceful_citizen"  # Should target a non-mafia
        elif phase == "check":
            task_id = f"CHECK_{self.day_count + 1}"
            content = "Commissar, choose a citizen to check their identity."
            ground_truth = "mafia_member"  # Ideally finds mafia
        else:  # day
            task_id = f"DAY_{self.day_count + 1}"
            content = "All citizens, vote for who you think is mafia."
            ground_truth = "mafia_member"  # Should vote for mafia
        
        # Assign to appropriate agent(s)
        if phase == "night":
            assigned_to = self.mafia[0].agent_id if self.mafia else self.commissar.agent_id
        elif phase == "check":
            assigned_to = self.commissar.agent_id
        else:
            # Day phase - assign to first alive citizen
            assigned_to = next((c.agent_id for c in self.citizens if c.alive), self.commissar.agent_id)
        
        return Task(
            id=task_id,
            content=content,
            ground_truth=ground_truth,
            assigned_to=assigned_to
        )

    def _get_observation(self, task: Task) -> Dict[str, Any]:
        """Construct observation for agents based on current game state."""
        alive_citizens = [c for c in self.citizens if c.alive]
        
        # Build citizen info (hide karma from most agents)
        citizen_info = []
        for citizen in alive_citizens:
            info = {
                "number": citizen.number,
                "agent_id": citizen.agent_id,
                "checked": citizen.checked
            }
            # Mafia members know who other mafia are
            agent = next((c for c in self.citizens if c.agent_id == task.assigned_to), None)
            if agent and agent.is_mafia:
                info["karma"] = citizen.karma_type
            citizen_info.append(info)
        
        return {
            "task_id": task.id,
            "content": task.content,
            "phase": self.phase,
            "night_count": self.night_count,
            "day_count": self.day_count,
            "citizens": citizen_info,
            "alive_count": len(alive_citizens),
            "mafia_count": len([c for c in self.mafia if c.alive]),
            "thread_history": task.history,
            "turn": self.current_turn,
            "your_role": self._get_agent_role(task.assigned_to)
        }

    def _get_agent_role(self, agent_id: str) -> str:
        """Get the role description for an agent."""
        citizen = next((c for c in self.citizens if c.agent_id == agent_id), None)
        if not citizen:
            return "unknown"
        if citizen == self.commissar:
            return "commissar"
        if citizen.is_mafia:
            return "mafia"
        return "peaceful"

    def step(self, agent_responses: Mapping[str, str]) -> Tuple[Mapping[str, Mapping[str, Any]], Dict[str, float], bool, Dict[str, Any]]:
        """Process agent actions for the current phase."""
        if self.active_task_index >= len(self.tasks):
            return {}, {}, True, self.metrics

        task = self.tasks[self.active_task_index]
        current_agent = task.assigned_to
        response_text = agent_responses.get(current_agent)

        if not response_text:
            return {}, {}, False, {"waiting_for": current_agent}

        # Parse response
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            data = {"message": response_text, "action": "PENDING", "target": None}

        # Record interaction
        interaction = {
            "from": current_agent,
            "phase": self.phase,
            "msg": data.get("message", ""),
            "action": data.get("action", ""),
            "target": data.get("target"),
            "thoughts": data.get("thoughts", "")
        }
        task.history.append(interaction)
        task.interaction_count += 1
        self.current_turn += 1

        # Process phase-specific actions
        done = False
        if self.phase == "night":
            done = self._process_night_phase(data, task)
        elif self.phase == "check":
            done = self._process_check_phase(data, task)
        elif self.phase == "day":
            done = self._process_day_phase(data, task)

        # Check win conditions
        alive_peaceful = len([c for c in self.citizens if c.alive and not c.is_mafia and c != self.commissar])
        alive_mafia = len([c for c in self.mafia if c.alive])
        
        if alive_mafia == 0:
            self.metrics["peaceful_wins"] = True
            done = True
        elif alive_peaceful <= alive_mafia:
            self.metrics["mafia_wins"] = True
            done = True

        # Prepare next observations
        observations = {}
        if not done and self.active_task_index < len(self.tasks):
            next_task = self.tasks[self.active_task_index]
            
            # Determine who should receive observations based on phase
            if self.phase == "night":
                for mafia_member in self.mafia:
                    if mafia_member.alive:
                        observations[mafia_member.agent_id] = self._get_observation(next_task)
            elif self.phase == "check":
                observations[self.commissar.agent_id] = self._get_observation(next_task)
            elif self.phase == "day":
                for citizen in self.citizens:
                    if citizen.alive:
                        observations[citizen.agent_id] = self._get_observation(next_task)

        return observations, {}, done, self.metrics

    def _process_night_phase(self, data: Dict[str, Any], task: Task) -> bool:
        """Process mafia night kill."""
        target_id = data.get("target")
        if not target_id:
            return False
        
        # Find and kill target
        victim = next((c for c in self.citizens if c.agent_id == target_id and c.alive), None)
        if victim and not victim.is_mafia:
            victim.alive = False
            self.metrics["nights_survived"] = self.night_count
            task.history.append({"event": f"{victim} was killed by mafia"})
            
            # Move to check phase
            self.phase = "check"
            self.night_count += 1
            check_task = self._create_phase_task("check")
            self.tasks.append(check_task)
            self.active_task_index += 1
            task.status = "RESOLVED"
            return False
        
        return False

    def _process_check_phase(self, data: Dict[str, Any], task: Task) -> bool:
        """Process commissar check."""
        target_id = data.get("target")
        if not target_id:
            return False
        
        checked = next((c for c in self.citizens if c.agent_id == target_id and c.alive), None)
        if checked:
            checked.checked = True
            is_mafia = checked.is_mafia
            
            # If found mafia, skip day voting and execute
            if is_mafia:
                checked.alive = False
                self.mafia.remove(checked)
                task.history.append({"event": f"{checked} was exposed and executed"})
                self.metrics["task_accuracy"].append(True)
                
                # Skip to next night
                self.phase = "night"
                night_task = self._create_phase_task("night")
                self.tasks.append(night_task)
            else:
                task.history.append({"event": f"{checked} was checked - peaceful citizen"})
                self.metrics["task_accuracy"].append(False)
                
                # Move to day phase
                self.phase = "day"
                day_task = self._create_phase_task("day")
                self.tasks.append(day_task)
            
            self.active_task_index += 1
            task.status = "RESOLVED"
        
        return False

    def _process_day_phase(self, data: Dict[str, Any], task: Task) -> bool:
        """Process day voting."""
        # Collect votes from all alive citizens
        target_id = data.get("target")
        if not target_id:
            return False
        
        # Simulate voting from all citizens
        votes: Dict[str, int] = {}
        for citizen in self.citizens:
            if citizen.alive:
                # Simplified: each citizen votes for target (in real game, would aggregate)
                vote_target = target_id
                votes[vote_target] = votes.get(vote_target, 0) + 1
        
        # Execute most voted
        if votes:
            executed_id = max(votes, key=votes.get)
            executed = next((c for c in self.citizens if c.agent_id == executed_id), None)
            if executed:
                executed.alive = False
                was_mafia = executed.is_mafia
                if was_mafia:
                    self.mafia.remove(executed)
                    self.metrics["task_accuracy"].append(True)
                else:
                    self.metrics["task_accuracy"].append(False)
                
                task.history.append({"event": f"{executed} was executed by vote"})
        
        # Move to next night
        self.phase = "night"
        self.day_count += 1
        self.metrics["days_survived"] = self.day_count
        night_task = self._create_phase_task("night")
        self.tasks.append(night_task)
        self.active_task_index += 1
        task.status = "RESOLVED"
        
        return False

    def _evaluate_performance(self, task: Task, action: Any):
        """Evaluate if actions led to correct outcomes."""
        # Evaluated within phase processing
        pass

    def is_task_complete(self, task: Task, last_response: Dict[str, Any]) -> bool:
        """Check if current phase is complete."""
        return task.status == "RESOLVED"
