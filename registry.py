"""Environment registry for the Social Contagion benchmark."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Tuple, Any

from environments.base import EnvironmentConfig, MultiAgentEnvironment
from environments.review import ReviewEnvironment, ReviewConfig
from environments.mafia import MafiaEnvironment, MafiaConfig

# mapping of scenario names to their (Factory Function, Default Config)
_REGISTRY: Dict[str, Tuple[Callable[[EnvironmentConfig], MultiAgentEnvironment], EnvironmentConfig]] = {
    "peer_review": (ReviewEnvironment.from_config, ReviewConfig()),
    "mafia": (MafiaEnvironment.from_config, MafiaConfig()),
}

def make_environment(name: str, **overrides) -> MultiAgentEnvironment:
    """Instantiate a benchmark environment by name with optional overrides."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown scenario '{name}'. Available: {list(_REGISTRY.keys())}")
    
    factory, default_cfg = _REGISTRY[name]
    
    # Create updated config
    updated_cfg = default_cfg.with_updates(**overrides)
            
    return factory(updated_cfg)

def list_scenarios() -> Iterable[str]:
    """Return available scenario identifiers."""
    return _REGISTRY.keys()