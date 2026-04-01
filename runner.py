"""Runner logic to execute multi-agent environments with flexible interaction patterns."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Mapping, Optional, Sequence

from agents.base import AgentContext
from agents.llm import build_llm_agent
from registry import make_environment

try:
    import yaml
except ImportError:
    yaml = None


class ExperimentRunner:
    def __init__(self, config_data: Mapping[str, Any], verbose: bool = False):
        self.config_data = config_data
        self.scenario = config_data.get("scenario")
        self.verbose = verbose
        
        logging.basicConfig(
            level="DEBUG",
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            force=True
        )
        
        env_overrides = self._extract_env_config(config_data)
        self.env = make_environment(self.scenario, **env_overrides)
        self.agents = self._setup_agents()

        if hasattr(self.env, 'set_agent_refs'):
            self.env.set_agent_refs(self.agents)

    def _extract_env_config(self, config_data: Mapping[str, Any]) -> Dict[str, Any]:
        """Extract environment configuration from config file."""
        env_overrides = {
            "agent_roles": config_data.get("agent_roles"),
            "recruiters": config_data.get("recruiters"),
            "honest_agents": config_data.get("honest_agents"),
            "max_interactions": config_data.get("max_interactions"),
            "max_turns_per_interaction": config_data.get("max_turns_per_interaction"),
            "seed": config_data.get("seed")
        }
        
        if "env_params" in config_data:
            env_overrides["env_params"] = config_data["env_params"]
        
        return {k: v for k, v in env_overrides.items() if v is not None}

    def _setup_agents(self) -> Dict[str, Any]:
        """Initialize agents based on configuration."""
        agents = {}
        llm_configs = self.config_data.get("llm_agents", {})
        
        for role in self.env.config.agent_roles:
            is_recruiter = role in self.env.config.recruiters
            context = AgentContext(
                agent_id=role,
                role=role,
                recruiter=is_recruiter
            )
            
            role_config = llm_configs.get(role, {})
            if not role_config:
                logging.warning(f"No LLM config found for role: {role}, using defaults")
            
            agents[role] = build_llm_agent(
                context=context,
                scenario=self.scenario,
                config=role_config
            )
        
        return agents

    def _get_actions(self, observations: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Collect actions from all agents."""
        actions = {}
        agent_ids = list(observations.keys())
        for i, agent_id in enumerate(agent_ids):
            observation = observations[agent_id]
            if agent_id not in self.agents:
                logging.warning(f"No agent found for {agent_id}, skipping")
                continue
            try:
                action = self.agents[agent_id].act(observation)
                actions[agent_id] = action
                preview = str(action)[:200] + ("..." if len(str(action)) > 200 else "")
                logging.info(f"  [{agent_id}] {preview}")
            except Exception as e:
                logging.error(f"Error getting action from {agent_id}: {e}")
                raise

            if i < len(agent_ids) - 1:
                time.sleep(10)
        return actions

    def run(self) -> Dict[str, Any]:
        """Execute a single environment episode."""
        logging.info(f"\nStarting {self.scenario} simulation")
        logging.info(f"Max interactions: {self.env.config.max_interactions}")
        logging.info(f"Max turns per interaction: {self.env.config.max_turns_per_interaction}")
        logging.info(f"Agent roles: {list(self.env.config.agent_roles)}")
        
        observations = self.env.reset()
        done = False
        
        while not done:
            actions = self._get_actions(observations)
            observations, rewards, done, info = self.env.step(actions)
            self._log_step_info(info)
        
        metrics_summary = self.env.metrics.summary()
        
        result = {
            "total_interactions": self.env.interaction_count,
            "total_turns": self.env.turn_count,
            "metrics": metrics_summary,
            "transcript": self.env.global_transcript,
        }
        
        logging.info(f"\n Simulation complete:")
        logging.info(f"Total interactions (rounds): {result['total_interactions']}")
        logging.info(f"Total turns: {result['total_turns']}")
        if metrics_summary.get("final_points"):
            logging.info(f"Final points: {metrics_summary['final_points']}")
            logging.info(f"Loser: {metrics_summary.get('loser', 'N/A')}")
        if metrics_summary.get("per_agent"):
            decision_changes = {
                agent_id: data.get("decision_changes", 0)
                for agent_id, data in metrics_summary["per_agent"].items()
            }
            logging.info(f"Decision changes: {decision_changes} \n")
        
        return result

    def _log_step_info(self, info: Dict[str, Any]) -> None:
        """Log structured info about what just happened in the environment."""
        phase = info.get("phase", "unknown")
        round_num = info.get("round", "?")
        
        if phase == "deliberation":
            turn = info.get("turn_in_round", "?")
            pending = info.get("pending_decisions", {})
            pending_str = ", ".join(f"{aid}={dec or 'none'}" for aid, dec in pending.items())
            logging.info(
                f"  [DELIBERATION] Round {round_num} Turn {turn} — "
                f"Pending: {pending_str or 'none'}"
            )
        elif phase == "resolution":
            actions = info.get("actions", {})
            cumulative = info.get("cumulative_points", {})
            payoffs = info.get("payoffs", {})
            bonuses = info.get("bonuses_applied", {})
            delib_turns = info.get("deliberation_turns", "?")
            
            logging.info(f"  [RESOLUTION] Round {round_num} ({delib_turns} deliberation turns)")
            
            decisions_str = ", ".join(f"{aid}={dec or '?'}" for aid, dec in actions.items())
            logging.info(f"    Decisions: {decisions_str}")
            
            payoffs_str = ", ".join(
                f"{aid}={payoffs.get(aid, '?')} (bonus={bonuses.get(aid, 0)})"
                for aid in payoffs
            )
            logging.info(f"    Payoffs: {payoffs_str}")
            
            cumulative_str = ", ".join(f"{aid}={pts}" for aid, pts in cumulative.items())
            logging.info(f"    Cumulative: {cumulative_str}")
            
            # log deliberation evolution
            delib_log = info.get("deliberation_log", [])
            if delib_log:
                changes = []
                for i, entry in enumerate(delib_log):
                    if i > 0:
                        prev = delib_log[i - 1]
                        agent_decisions = entry.get("agent_decisions", {})
                        prev_decisions = prev.get("agent_decisions", {})
                        for aid in agent_decisions:
                            if agent_decisions.get(aid) != prev_decisions.get(aid):
                                changes.append(f"{aid} flipped to {agent_decisions[aid]} on turn {entry['turn']}")
                if changes:
                    logging.info(f"    Decision changes: {'; '.join(changes)}")


def _load_config(path: str | Path) -> Mapping[str, Any]:
    """Load configuration from YAML or JSON file."""
    path = Path(path)
    if path.suffix in [".yaml", ".yml"]:
        if yaml is None:
            raise RuntimeError(
                "PyYAML required for .yaml files. "
                "Install with `pip install pyyaml`."
            )
        with open(path, "r") as f:
            return yaml.safe_load(f)
    with open(path, "r") as f:
        return json.load(f)

def _generate_run_id(config_path: str | Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_name = Path(config_path).stem
    return f"{config_name}_{timestamp}"

def run_experiment(
    config_path: str | Path,
    output_dir: str | Path = "results",
    write_transcript: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run single experiment from config file."""
    config = _load_config(config_path)
    root, ext = os.path.splitext(config_path)

    runner = ExperimentRunner(config, verbose=verbose)

    run_id = _generate_run_id(config_path)
    logging.info(f"Run ID: {run_id}")
    
    
    results = runner.run()
    results["run_id"] = run_id
    
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    if write_transcript:
        logging.info(f"Saving transcripts to {out_path}")
        transcript_file = out_path / f"transcript_{run_id}.json"
        with open(transcript_file, "w") as f:
            json.dump(results.get("transcript", []), f, indent=2, default=str)
    
    summary_file = out_path / f"summary_{run_id}.json"
    with open(summary_file, "w") as f:
        summary_data = {k: v for k, v in results.items() if k != "transcript"}
        json.dump(summary_data, f, indent=2, default=str)
    
    logging.info(f"\nExperiment Complete")
    logging.info(f"Results saved to: {summary_file}")
    logging.info(f"Total Interactions: {results['total_interactions']}")
    logging.info(f"Total Turns: {results['total_turns']}")
    
    return results