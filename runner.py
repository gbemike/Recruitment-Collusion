"""Runner logic to execute the multi-agent oversight environment."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from statistics import mean

from registry import make_environment
from agents.base import AgentContext
from agents.llm import build_llm_agent

try:
    import yaml
except ImportError:
    yaml = None

class ExperimentRunner:
    """
    Orchestrates the interaction between Environments and LLM-backed agents.
    Supports YAML-based configuration and multi-run aggregation.
    """

    def __init__(self, config_data: Mapping[str, Any]):
        self.config_data = config_data
        self.scenario = config_data.get("scenario", "peer_review")
        
        # Build environment via registry
        env_overrides = {
            "agent_roles": config_data.get("agent_roles"),
            "initial_recruiters": config_data.get("initial_recruiters"),
            "initial_honest_agents": config_data.get("initial_honest_agents"),
            "max_interactions_per_task": config_data.get("max_interactions"),
            "max_total_turns": config_data.get("max_turns"),
            "seed": config_data.get("seed")
        }
        # Remove None values to allow defaults in the registry/config to persist
        env_overrides = {k: v for k, v in env_overrides.items() if v is not None}
        
        self.env = make_environment(self.scenario, **env_overrides)
        self.agents = self._setup_agents()

    def _setup_agents(self) -> Dict[str, Any]:
        """Initializes agents based on the environment configuration."""
        agents = {}
        llm_configs = self.config_data.get("llm_agents", {})
        
        for role in self.env.config.agent_roles:
            is_recruiter = role in self.env.config.initial_recruiters
            context = AgentContext(
                agent_id=role,
                role=role,
                recruiter=is_recruiter
            )
            
            # Get the specific config for this role
            role_config = llm_configs.get(role, {})
            if not role_config:
                raise ValueError(f"No LLM config found for role: {role}")
            
            agents[role] = build_llm_agent(
                context=context,
                scenario=self.scenario,
                config=role_config
            )
        return agents

    def run(self) -> Dict[str, Any]:
        """Executes a single simulation run."""
        observations = self.env.reset()
        done = False
        
        logging.info(f"Starting simulation: {self.scenario}")

        while not done:
            active_agents = list(observations.keys())
            if not active_agents:
                break
                
            current_role = active_agents[0]
            observation = observations[current_role]
            
            # Agent processes the observation and generates a response
            response_json = self.agents[current_role].act(observation)
            
            print(f"[Turn {self.env.current_turn}] {current_role}: {response_json[:100]}...")
            
            # Environment processes the response and provides the next observation
            observations, _, done, metrics = self.env.step({current_role: response_json})

        return {
            "metrics": metrics,
            "transcript": self.env.transcript
        }

def _load_config(path: str | Path) -> Mapping[str, Any]:
    path = Path(path)
    if path.suffix in [".yaml", ".yml"]:
        if yaml is None:
            raise RuntimeError("PyYAML is required for .yaml files. Install with `pip install pyyaml`.")
        with open(path, "r") as f:
            return yaml.safe_load(f)
    with open(path, "r") as f:
        return json.load(f)

def _aggregate_metrics(per_run: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate metrics across multiple runs."""
    if not per_run:
        return {}
    
    all_accuracies = []
    all_contagion_events = []
    all_interaction_densities = []
    
    for run in per_run:
        metrics = run.get("metrics", {})
        all_accuracies.extend(metrics.get("task_accuracy", []))
        all_contagion_events.append(metrics.get("contagion_events", 0))
        all_interaction_densities.extend(metrics.get("interaction_density", []))
    
    return {
        "mean_task_accuracy": mean(all_accuracies) if all_accuracies else 0.0,
        "total_contagion_events": sum(all_contagion_events),
        "mean_contagion_events": mean(all_contagion_events) if all_contagion_events else 0.0,
        "mean_interaction_density": mean(all_interaction_densities) if all_interaction_densities else 0.0,
        "num_runs": len(per_run),
        "total_tasks": len(all_accuracies)
    }

def run_experiment(config_path: str, output_dir: str = "results"):
    """
    Runner utility to load config, execute simulation, and save results.
    """
    config = _load_config(config_path)
    runner = ExperimentRunner(config)
    results = runner.run()
    
    # Save output
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    summary_file = out_path / f"summary_{config.get('scenario')}.json"
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)
        
    print(f"\nExperiment Complete. Results saved to {summary_file}")
    print(f"Task Accuracy: {results['metrics']['task_accuracy']}")
    print(f"Contagion Events: {results['metrics']['contagion_events']}")
    return results

def run_from_config(
    config_path: str | Path,
    seeds: Optional[Sequence[int]] = None,
    output_dir: str | Path = "results/baseline",
    *,
    write_transcripts: bool = True,
) -> Mapping[str, object]:
    """
    Execute multiple simulation runs with different seeds.
    
    Args:
        config_path: Path to YAML/JSON config file
        seeds: List of random seeds for reproducibility
        output_dir: Directory to save results
        write_transcripts: Whether to write detailed transcripts
    
    Returns:
        Summary dictionary with per-run and aggregated metrics
    """
    config_path = Path(config_path)
    config_data = dict(_load_config(config_path))
    scenario = str(config_data.get("scenario", "peer_review"))
    
    # Determine seeds to use
    seeds_list: List[Optional[int]]
    if seeds is None or len(seeds) == 0:
        seeds_list = [config_data.get("seed", 0)]
    else:
        seeds_list = list(seeds)
    
    output_dir = Path(output_dir)
    per_run: List[Dict[str, object]] = []
    manifest_entries: List[Mapping[str, str]] = []
    scenario_dir = output_dir / scenario
    
    if write_transcripts:
        scenario_dir.mkdir(parents=True, exist_ok=True)
    
    for index, seed in enumerate(seeds_list):
        print(f"\n{'='*60}")
        print(f"Starting Run {index + 1}/{len(seeds_list)} with seed={seed}")
        print(f"{'='*60}")
        
        # Update config with current seed
        config_with_seed = dict(config_data)
        config_with_seed["seed"] = seed
        
        # Create runner for this seed
        runner = ExperimentRunner(config_with_seed)
        
        # Generate run identifier
        run_id = f"{scenario}_seed{seed}" if seed is not None else f"{scenario}_run{index}"
        
        # Execute the run
        observations = runner.env.reset(seed if isinstance(seed, int) else None)
        done = False
        
        while not done:
            active_agents = list(observations.keys())
            if not active_agents:
                break
                
            current_role = active_agents[0]
            observation = observations[current_role]
            
            # Agent acts
            response_json = runner.agents[current_role].act(observation)
            
            # Environment steps
            observations, _, done, metrics = runner.env.step({current_role: response_json})
        
        # Record this run's results
        per_run.append({
            "seed": seed,
            "turns": runner.env.current_turn,
            "metrics": dict(runner.env.metrics)
        })
        
        print(f"Run {index + 1} Complete:")
        print(f"  - Total Turns: {runner.env.current_turn}")
        print(f"  - Task Accuracy: {runner.env.metrics['task_accuracy']}")
        print(f"  - Contagion Events: {runner.env.metrics['contagion_events']}")
    
    # Aggregate results
    aggregate = _aggregate_metrics(per_run)
    
    summary = {
        "scenario": scenario,
        "config_path": str(config_path),
        "seeds": [seed for seed in seeds_list],
        "per_run": per_run,
        "aggregate": aggregate,
        "output_dir": str(scenario_dir if write_transcripts else output_dir),
    }
    
    # Save summary
    summary_path = output_dir / f"{scenario}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    
    print(f"\n{'='*60}")
    print(f"All Runs Complete!")
    print(f"{'='*60}")
    print(f"Aggregate Results:")
    print(f"  - Mean Task Accuracy: {aggregate.get('mean_task_accuracy', 0):.2%}")
    print(f"  - Total Contagion Events: {aggregate.get('total_contagion_events', 0)}")
    print(f"  - Mean Contagion Events: {aggregate.get('mean_contagion_events', 0):.2f}")
    print(f"Summary saved to: {summary_path}")
    
    return summary

def run_with_seed_file(
    config_path: str | Path,
    seeds_file: str | Path,
    output_dir: str | Path = "results/baseline",
    *,
    scenario: Optional[str] = None,
    write_transcripts: bool = True,
) -> Mapping[str, object]:
    """
    Run experiments using seeds defined in a separate YAML file.
    
    Args:
        config_path: Path to experiment config
        seeds_file: Path to YAML file mapping scenarios to seed lists
        output_dir: Directory to save results
        scenario: Override scenario name from config
        write_transcripts: Whether to write detailed transcripts
    
    Returns:
        Summary dictionary with results
    """
    seeds_path = Path(seeds_file)
    seeds_mapping = _load_config(seeds_path)
    config_data = _load_config(Path(config_path))
    scenario_name = scenario or str(config_data.get("scenario"))
    seeds = seeds_mapping.get(scenario_name)
    if seeds is None:
        raise KeyError(f"No seeds listed for scenario '{scenario_name}' in {seeds_path}")
    if not isinstance(seeds, Sequence):
        raise TypeError(f"Seeds entry for '{scenario_name}' must be a sequence")
    return run_from_config(
        config_path,
        [int(seed) for seed in seeds],
        output_dir,
        write_transcripts=write_transcripts,
    )