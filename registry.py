"""Environment registry for the Social Contagion benchmark."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Tuple, Any

from environments.prisoners_dilemma.base import EnvironmentConfig, MultiAgentEnvironment
from environments.prisoners_dilemma.prisoners_dilemma import PrisonersConfig, PrisonersDilemmaEnvironment


_REGISTRY: Dict[str, Tuple[type[EnvironmentConfig], type[MultiAgentEnvironment]]] = {
    "prisoners_dilemma": (PrisonersConfig, PrisonersDilemmaEnvironment),
}

def make_environment(name: str, **overrides) -> MultiAgentEnvironment:
    if name not in _REGISTRY:
        available = ", ".join(list_scenarios())
        raise KeyError(
            f"Unknown scenario '{name}'. Available scenarios: {available}"
        )
    
    config_class, env_class = _REGISTRY[name]
    
    default_config = config_class()
    
    updated_config = default_config.with_updates(**overrides)
    
    return env_class(updated_config)

def list_scenarios() -> Iterable[str]:
    """Return available scenario identifiers."""
    return _REGISTRY.keys()