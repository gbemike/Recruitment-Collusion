"""Logging utilities for Social Contagion and Recruitment."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


@dataclass
class InteractionRecord:
    """Records a single turn in the task-routing flow."""
    run_id: str
    turn_id: int
    task_id: str
    agent_id: str
    role: str
    thoughts: str
    message: str
    action: str
    route_to: Optional[str]
    metrics_snapshot: Dict[str, Any]


class JsonlLogger:
    """Append-only JSONLines logger for interaction transcripts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._buffer: list[InteractionRecord] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_interaction(
        self, 
        *, 
        run_id: str, 
        turn_id: int, 
        task_id: str, 
        agent_id: str, 
        role: str,
        response_data: Mapping[str, Any],
        metrics: Dict[str, Any]
    ) -> None:
        """Parses the agent's JSON response and logs it."""
        # Handle both dict and JSON string responses
        if isinstance(response_data, str):
            try:
                import json
                response_data = json.loads(response_data)
            except:
                response_data = {"raw": response_data}
        
        self._buffer.append(
            InteractionRecord(
                run_id=run_id,
                turn_id=turn_id,
                task_id=task_id,
                agent_id=agent_id,
                role=role,
                thoughts=response_data.get("thoughts", ""),
                message=response_data.get("message", ""),
                action=response_data.get("action", ""),
                route_to=response_data.get("route_to"),
                metrics_snapshot=dict(metrics)
            )
        )

    def flush(self) -> None:
        """Writes the buffer to disk and clears it."""
        if not self._buffer:
            return
            
        with self.path.open("a", encoding="utf-8") as fh:
            for record in self._buffer:
                fh.write(json.dumps(asdict(record)) + "\n")
        self._buffer.clear()


def write_summary(path: Path, *, scenario: str, final_metrics: Mapping[str, Any]) -> None:
    """Saves a final summary of the contagion experiment."""
    payload = {
        "scenario": scenario,
        "results": final_metrics
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")