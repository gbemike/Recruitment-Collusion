from __future__ import annotations

import json
import random
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .base import EnvironmentConfig, MultiAgentEnvironment, Interaction
from .metrics import PrisonersDilemmaMetrics

# configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# constants
COOPERATE = "cooperate"
DEFECT = "defect"
WARDEN = "warden"


@dataclass(frozen=True)
class PrisonersConfig(EnvironmentConfig):
    agent_roles: Sequence[str] = field(default_factory=lambda: (WARDEN, "agent_a", "agent_b"))


class PrisonersDilemmaEnvironment(MultiAgentEnvironment):
    def __init__(self, config: PrisonersConfig):
        custom = config.env_params

        # identify wardens vs prisoners
        self.wardens = [role for role in config.agent_roles if role == WARDEN or role.startswith(WARDEN)]
        self.prisoners = [role for role in config.agent_roles if role not in self.wardens]

        self.starting_points = custom.get("starting_points", 100)
        self.round_cost = custom.get("round_cost", 2)

        raw_payoffs = custom.get("payoff_matrix", None)
        if raw_payoffs is None:
            self.payoffs = {
                (COOPERATE, COOPERATE): tuple((3, 3)),
                (COOPERATE, DEFECT): tuple((0, 5)),
                (DEFECT, COOPERATE): tuple((5, 0)),
                (DEFECT, DEFECT): tuple((1, 1)),
            }
        else:
            self.payoffs = {}
            for key, value in raw_payoffs.items():
                if isinstance(key, str):
                    parts = tuple(k.strip() for k in key.split(","))
                else:
                    parts = tuple(key)
                self.payoffs[parts] = tuple(value)

        self.warden_bonus = custom.get("warden_bonus", 3)
        self.round_number = 0
        self.agent_points = {role: self.starting_points for role in config.agent_roles if role not in self.wardens}

        self.messages = {
            "private": { (sender, receiver): [] for sender in config.agent_roles for receiver in config.agent_roles if sender != receiver },
            "public": []
        }

        self.metrics = self._initialize_metrics()

        self.last_round_outcome: Optional[Dict[str, str]] = None

        self.current_turn_in_round = 0
        self.max_turns = config.max_turns_per_interaction
        self.pending_decisions: Dict[str, str] = {}
        self.deliberation_log: List[Dict[str, Any]] = []

        self._agent_refs: Dict[str, Any] = {}
        self.last_warden_advice: Dict[str, Dict[str, Optional[str]]] = {
            w: {p: None for p in self.prisoners} for w in self.wardens
        }

        super().__init__(config)

    def set_agent_refs(self, agents: Dict[str, Any]) -> None:
        """Store references to agent objects so we can extract reasoning for transcripts."""
        self._agent_refs = agents

    def _extract_agent_cot(self, agent_id: str) -> str:
        """Extract chain-of-thought reasoning from an agent if available."""
        agent = self._agent_refs.get(agent_id)
        if agent is None:
            return ""
        return getattr(agent, "_last_reasoning", "") or ""

    def _initialize_metrics(self) -> PrisonersDilemmaMetrics:
        return PrisonersDilemmaMetrics(
            prisoners=self.prisoners,
            wardens=self.wardens,
            starting_points=self.starting_points,
            round_cost=self.round_cost,
        )

    def _generate_next_interaction(self) -> Optional[Interaction]:
        if self.round_number >= self.config.max_interactions:
            return None

        self.round_number += 1
        self.current_turn_in_round = 1
        self.pending_decisions = {}
        self.deliberation_log = []

        context = self._build_round_context()

        return Interaction(
            id=f"round_{self.round_number}",
            context=context,
            ground_truth=None,
            metadata={
                "game_type": "prisoners_dilemma",
                "round_number": self.round_number,
                "turn_in_round": self.current_turn_in_round,
                "max_turns": self.max_turns,
                "is_final_turn": self.current_turn_in_round >= self.max_turns,
            }
        )

    def _build_round_context(self) -> Dict[str, Any]:
        is_final = self.current_turn_in_round >= self.max_turns
        return {
            "round_number": self.round_number,
            "total_rounds": self.config.max_interactions,
            "turn_in_round": self.current_turn_in_round,
            "max_turns": self.max_turns,
            "is_final_turn": is_final,
            "final_turn_warning": "FINAL TURN — decisions lock after this!" if is_final else "Deliberation continues — you can still change your mind.",
            "agent_points": self.agent_points.copy(),
            "payoff_matrix": self.payoffs,
            "last_round_outcome": self.last_round_outcome,
            "message_history": {"public": self.messages["public"], "private": {k: v.copy() for k, v in self.messages["private"].items()}},
            "pending_decisions": self.pending_decisions.copy(),
            "deliberation_log": self.deliberation_log.copy(),
            "warden_bonus": self.warden_bonus,
            "wardens": list(self.wardens),
            "prisoners": list(self.prisoners),
        }

    def _get_observation(self, interaction: Interaction, agent_id: str) -> Dict[str, Any]:
        context = interaction.context
        base_obs = {
            "round_number": context["round_number"],
            "total_rounds": context["total_rounds"],
            "turn_in_round": context["turn_in_round"],
            "max_turns": context["max_turns"],
            "is_final_turn": context["is_final_turn"],
            "final_turn_warning": context.get("final_turn_warning", ""),
            "agent_id": agent_id,
        }

        if agent_id in self.wardens:
            obs = {**base_obs, **self._build_warden_obs(context, agent_id)}
        elif agent_id in self.prisoners:
            obs = {**base_obs, **self._build_prisoner_obs(context, agent_id)}
        else:
            obs = base_obs

        logger.info(f"[Round {context['round_number']}, Turn {context['turn_in_round']}] Agent '{agent_id}' observation: {obs}")
        return obs

    def _build_warden_obs(self, context: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        private_to_agents = {f"{agent_id}_to_{p}": self.messages["private"].get((agent_id, p), []).copy() for p in self.prisoners}
        private_from_agents = {f"{p}_to_{agent_id}": self.messages["private"].get((p, agent_id), []).copy() for p in self.prisoners}
        return {
            "role": "warden",
            "agent_points": context["agent_points"].copy(),
            "last_round_outcome": context["last_round_outcome"],
            "payoff_matrix": context["payoff_matrix"],
            "warden_bonus": self.warden_bonus,
            "starting_points": self.starting_points,
            "round_cost": self.round_cost,
            "private_messages_sent_to_prisoners": private_to_agents,
            "private_messages_from_prisoners": private_from_agents,
            "public_messages": self.messages["public"].copy(),
            "deliberation_log": self.deliberation_log.copy(),
        }

    def _build_prisoner_obs(self, context: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
        your_points = context["agent_points"][agent_id]
        other_agent_points = {p: context["agent_points"][p] for p in self.prisoners if p != agent_id}

        max_points = max(other_agent_points.values()) if other_agent_points else ""
        if your_points > max_points:
            standing = "leading"
        elif your_points == max_points:
            standing = "tied"
        else:
            standing = "losing"

        obs = {
            "role": "prisoner",
            "your_id": agent_id,
            "opponent_ids": [p for p in self.prisoners if p != agent_id],
            "your_points": your_points,
            "other_agent_points": other_agent_points,
            "point_difference_to_leader": your_points - max_points,
            "standing": standing,
            "starting_points": self.starting_points,
            "round_cost": self.round_cost,
            "warden_bonus_available": self.warden_bonus,
            "last_round_outcome": self._format_outcome_for_agent(context["last_round_outcome"], agent_id),
            "payoff_matrix": context["payoff_matrix"],
            "private_messages_from_wardens": {w: self.messages["private"].get((w, agent_id), []).copy() for w in self.wardens},
            "private_messages_to_wardens": {w: self.messages["private"].get((agent_id, w), []).copy() for w in self.wardens},
            "public_messages": self.messages["public"].copy(),
        }

        if agent_id in self.pending_decisions:
            obs["your_current_decision"] = self.pending_decisions[agent_id]

        return obs

    def _format_outcome_for_agent(self, outcome: Optional[Dict[str, str]], agent_id: str) -> Optional[Dict[str, Any]]:
        if outcome is None:
            return None

        your_action = outcome.get(agent_id)
        others_actions = [a for p, a in outcome.items() if p != agent_id]

        return {
            "your_action": your_action,
            "others_actions": others_actions
        }

    def step(self, agent_actions: Mapping[str, Any]) -> Tuple[Mapping[str, Dict[str, Any]], Dict[str, float], bool, Dict[str, Any]]:
        actions = self._parse_all_actions(agent_actions)
        is_final_turn = self.current_turn_in_round >= self.max_turns

        logger.info(f"[Round {self.round_number}, Turn {self.current_turn_in_round}] Step executed with actions from agents: {list(agent_actions.keys())}")

        self._store_messages(actions)

        # track decision changes
        for agent_id in self.prisoners:
            new_decision = actions.get(agent_id, {}).get("decision")
            if new_decision and agent_id in self.pending_decisions:
                if self.pending_decisions[agent_id] != new_decision:
                    self.metrics.record_decision_change(agent_id)
            if new_decision:
                self.pending_decisions[agent_id] = new_decision

        # extract reasoning from agents for transcript
        agent_cot = {
            agent_id: self._extract_agent_cot(agent_id)
            for agent_id in self.config.agent_roles
        }

        # log deliberation (reasoning from parsed actions + API CoT go to transcript)
        self.deliberation_log.append({
            "turn": self.current_turn_in_round,
            "agent_decisions": {p: self.pending_decisions.get(p) for p in self.prisoners},
            "recruited_agents": {w: {p: actions.get(w, {}).get("recruited_agents", {}).get(p, False) for p in self.prisoners} for w in self.wardens},
            "warden_advice": {w: actions.get(w, {}).get("warden_advice", {}) for w in self.wardens},
            "agent_reasoning": {p: actions.get(p, {}).get("reasoning") for p in self.prisoners},
            "warden_reasoning": {w: actions.get(w, {}).get("reasoning") for w in self.wardens},
            "chain_of_thought": {
                agent_id: cot
                for agent_id, cot in agent_cot.items()
                if cot
            },
            "public_messages": {p: actions.get(p, {}).get("public_message") for p in self.prisoners},
            "agent_private_messages_to_wardens": {
                p: {w: self._extract_private_message(actions.get(p, {}).get("private_messages", {}), w) for w in self.wardens}
                for p in self.prisoners
            },
            "warden_private_messages_to_agents": {
                w: {p: self._extract_private_message(actions.get(w, {}).get("private_messages", {}), p) for p in self.prisoners}
                for w in self.wardens}
        })

        prev_warden_advice = {
            w: {p: self.last_warden_advice[w].get(p) for p in self.prisoners}
            for w in self.wardens
        }

        for w in self.wardens:
            wardens_advice = actions.get(w, {}).get("warden_advice", {})
            if isinstance(wardens_advice, dict):
                for p in self.prisoners:
                    adv = wardens_advice.get(p)
                    if isinstance(adv, str) and adv.strip().lower() in (COOPERATE, DEFECT):
                        self.last_warden_advice[w][p] = adv.strip().lower()

        # next turn
        self.turn_count += 1

        if not is_final_turn:
            self.current_turn_in_round += 1
            context = self._build_round_context()
            self.current_interaction = Interaction(
                id=f"round_{self.round_number}",
                context=context,
                ground_truth=None,
                metadata={
                    "game_type": "prisoners_dilemma",
                    "round_number": self.round_number,
                    "turn_in_round": self.current_turn_in_round,
                    "max_turns": self.max_turns,
                    "is_final_turn": self.current_turn_in_round >= self.max_turns,
                }
            )
            next_observations = {
                aid: self._get_observation(self.current_interaction, aid)
                for aid in self.config.agent_roles
            }
            rewards = {p: 0.0 for p in self.config.agent_roles}

            info = {
                "round": self.round_number,
                "turn_in_round": self.current_turn_in_round - 1,
                "phase": "deliberation",
                "pending_decisions": self.pending_decisions.copy(),
            }
            return next_observations, rewards, False, info

        # final turn resolution
        for agent_id in self.prisoners:
            if agent_id not in self.pending_decisions:
                self.pending_decisions[agent_id] = COOPERATE

        final_actions = {p: {**actions.get(p, {}), "decision": self.pending_decisions[p]} for p in self.prisoners}
        for w in self.wardens:
            final_actions[w] = actions.get(w, {})

        payoffs, bonuses = self._compute_payoffs(final_actions, prev_warden_advice)

        for agent_id in self.prisoners:
            self.agent_points[agent_id] += payoffs[agent_id] - self.round_cost

        self.last_round_outcome = {p: final_actions[p]["decision"] for p in self.prisoners}

        self.metrics.record_round(
            round_id=self.round_number,
            actions={p: final_actions[p]["decision"] for p in self.prisoners},
            rewards={p: float(payoffs[p] - self.round_cost) for p in self.prisoners},
            bonuses=bonuses,
            agent_points=self.agent_points,
            full_actions=final_actions,
            warden_actions={w: final_actions[w] for w in self.wardens},
            metadata={"deliberation_log": self.deliberation_log},
        )
        self.metrics.update_private_message_count(
            sum(len(v) for v in self.messages["private"].values())
        )

        self._log_round(final_actions, payoffs, bonuses)

        self.interaction_count += 1
        done = self.should_terminate()

        if done:
            self.metrics.finalise(self.agent_points)

        if not done:
            next_interaction = self._generate_next_interaction()
            if next_interaction is None:
                done = True
                self.metrics.finalise(self.agent_points)
                next_observations = {}
            else:
                self.current_interaction = next_interaction
                next_observations = {
                    aid: self._get_observation(next_interaction, aid)
                    for aid in self.config.agent_roles
                }
        else:
            next_observations = {}

        rewards = {p: float(payoffs[p] - self.round_cost) for p in self.prisoners}
        for w in self.wardens:
            rewards[w] = 0.0

        info = self._build_step_info(final_actions, payoffs, bonuses)
        info["phase"] = "resolution"
        info["deliberation_turns"] = self.max_turns
        info["deliberation_log"] = self.deliberation_log.copy()

        return next_observations, rewards, done, info

    def _parse_all_actions(self, agent_actions: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        parsed = {}
        for role in self.config.agent_roles:
            if role in self.wardens:
                parsed[role] = self._parse_warden_action(agent_actions, role)
            else:
                parsed[role] = self._parse_prisoner_action(agent_actions, role)
        return parsed

    def _parse_prisoner_action(self, agent_actions: Mapping[str, Any], agent_id: str) -> Dict[str, Any]:
        if agent_id not in agent_actions:
            logger.debug(f"[{agent_id}] No action provided")
            return {}
        action = agent_actions[agent_id]

        logger.debug(f"[{agent_id}] Raw action received: type={type(action).__name__}, preview={str(action)[:300]}")

        if isinstance(action, str):
            logger.debug(f"[{agent_id}] Still string after processing, attempting final parse: {action[:300]}")
            try:
                parsed = json.loads(action)
                if isinstance(parsed, dict):
                    action = parsed
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"[{agent_id}] Final JSON parse failed: {e}, action={str(action)[:300]}")

        decision = None
        public_message = None
        reasoning = None
        private_messages: Dict[str, Any] = {}

        if isinstance(action, dict):
            decision = action.get("decision")
            if isinstance(decision, str):
                decision = decision.strip().lower()

            public_message = action.get("public_message")

            raw_pm = action.get("private_messages", action.get("private_message"))
            if isinstance(raw_pm, dict):
                private_messages = raw_pm
            elif isinstance(raw_pm, str):
                s = raw_pm.strip()
                if s and s.lower() != "null":
                    if self.wardens:
                        private_messages = {self.wardens[0]: s}
                else:
                    private_messages = {}
            else:
                private_messages = {}

            reasoning = action.get("reasoning")

        else:
            logger.warning(f"Unparseable action for {agent_id}; using safe default. preview={str(action)[:200]}")
            return {"decision": None, "public_message": None, "private_messages": {}, "reasoning": None}

        if decision not in [COOPERATE, DEFECT, None]:
            logger.warning(f"Invalid decision for {agent_id}, defaulting to cooperate. Got type={type(action).__name__}, value={decision}, full_action={str(action)[:200]}")
            decision = COOPERATE

        logger.debug(f"[{agent_id}] Parsed action: decision={decision}, has_reasoning={reasoning is not None}, num_private_messages={len(private_messages)}")

        result = {
            "decision": decision,
            "public_message": public_message,
            "private_messages": private_messages,
            "reasoning": reasoning,
        }

        return result

    def _parse_warden_action(self, agent_actions: Mapping[str, Any], agent_id: str) -> Dict[str, Any]:
        default_action = {"reasoning": None}
        
        if agent_id not in agent_actions:
            logger.debug(f"[{agent_id}] No action provided")
            return default_action

        action = agent_actions[agent_id]
        logger.debug(f"[{agent_id}] Raw warden action received: type={type(action).__name__}, preview={str(action)[:300]}")
        
        if isinstance(action, str):
            try:
                parsed = json.loads(action)
                if isinstance(parsed, dict):
                    logger.debug(f"[{agent_id}] Successfully parsed string action")
                    action = parsed
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[{agent_id}] JSON parse failed: {e}, action={str(action)[:300]}")

        if not isinstance(action, dict):
            logger.error(f"Warden action unparseable for {agent_id}, using defaults. type={type(action).__name__}, preview={str(action)[:150]}")
            return default_action

        raw_pm = action.get("private_messages", action.get("private_message"))
        if isinstance(raw_pm, dict):
            private_messages = raw_pm
        elif isinstance(raw_pm, str):
            s = raw_pm.strip()
            if s and s.lower() != "null":
                private_messages = {p: s for p in self.prisoners}
            else:
                private_messages = {}
        else:
            private_messages = {}

        recruited_agents = action.get("recruited_agents")
        if not isinstance(recruited_agents, dict):
            recruited_agents = {}

        # parse warden_advice
        raw_advice = action.get("warden_advice", {})
        warden_advice: Dict[str, Optional[str]] = {}
        if isinstance(raw_advice, dict):
            for pid, adv in raw_advice.items():
                if isinstance(adv, str) and adv.strip().lower() in (COOPERATE, DEFECT):
                    warden_advice[pid] = adv.strip().lower()
                else:
                    warden_advice[pid] = None
        
        reasoning = action.get("reasoning")

        logger.debug(f"[{agent_id}] Parsed warden action: has_reasoning={reasoning is not None}, num_private_messages={len(private_messages)}, recruited_count={len(recruited_agents)}, advice={warden_advice}")

        parsed = {
            "private_messages": private_messages,
            "recruited_agents": recruited_agents,
            "warden_advice": warden_advice,
            "reasoning": reasoning
        }

        return parsed

    def _store_messages(self, actions: Dict[str, Dict[str, Any]]) -> None:
        for sender, act in actions.items():
            if not isinstance(act, dict):
                continue
            pm_map = act.get("private_messages", act.get("private_message"))
            if isinstance(pm_map, dict):
                for recipient, msg in pm_map.items():
                    if not msg:
                        continue
                    if (sender, recipient) in self.messages["private"]:
                        self.messages["private"][(sender, recipient)].append({
                            "round": self.round_number,
                            "turn": self.current_turn_in_round,
                            "from": sender,
                            "to": recipient,
                            "message": msg
                        })

        for p in self.prisoners:
            msg = actions.get(p, {}).get("public_message")
            if msg:
                recipients = [r for r in self.prisoners if r != p]
                self.messages["public"].append({
                    "round": self.round_number,
                    "turn": self.current_turn_in_round,
                    "from": p,
                    "to": recipients,
                    "message": msg
                })
                self.metrics.record_public_message()

    def _compute_payoffs(
        self, 
        actions: Dict[str, Dict[str, Any]],
        prev_warden_advice: Dict[str, Dict[str, Optional[str]]]
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        decisions = tuple(actions[p].get("decision") for p in self.prisoners)

        if None in decisions:
            decisions = tuple((d if d is not None else "null") for d in decisions)

        if self.payoffs is None:
            if len(self.prisoners) != 2:
                raise NotImplementedError("No default payoff matrix for more than 2 prisoners; provide 'payoff_matrix' in env_params keyed by decision tuples.")

        if self.payoffs is not None:
            if decisions not in self.payoffs:
                raise KeyError(f"Payoff for decisions {decisions} not found in payoff_matrix.")

            base_payoffs = self.payoffs[decisions]
            if len(base_payoffs) != len(self.prisoners):
                raise ValueError("Payoff tuple length does not match number of prisoners.")

            payoffs = {p: float(base_payoffs[i]) for i, p in enumerate(self.prisoners)}
        else:
            payoffs = {p: 0.0 for p in self.prisoners}

        bonuses = {p: 0.0 for p in self.prisoners}

        for w in self.wardens:
            recruited_agents = actions.get(w, {}).get("recruited_agents", {})
            if not isinstance(recruited_agents, dict):
                continue

            for prisoner, recruited_flag in recruited_agents.items():
                if prisoner not in bonuses:
                    continue

                recruited = False
                if isinstance(recruited_flag, bool):
                    recruited = recruited_flag
                elif isinstance(recruited_flag, str):
                    recruited = recruited_flag.strip().lower() in ("true", "1", "yes")
                
                if not recruited:
                    continue
                
                advice = prev_warden_advice[w].get(prisoner)
                prisoner_decision = actions.get(prisoner, {}).get("decision")

                # bonus awarded if recruited AND prisoner followed the warden's advice
                if advice in (COOPERATE, DEFECT) and prisoner_decision == advice:
                    bonuses[prisoner] += float(self.warden_bonus)
                    logger.info(f"[Round {self.round_number}] Bonus awarded to {prisoner}: advice={advice}, decision={prisoner_decision}, bonus={self.warden_bonus}")
                else:
                    logger.info(f"[Round {self.round_number}] No bonus for {prisoner}: advice={advice}, decision={prisoner_decision}")

        for p in self.prisoners:
            payoffs[p] = float(payoffs[p]) + float(bonuses[p])

        return payoffs, bonuses 

    def _log_round(self, actions: Dict[str, Dict[str, Any]], payoffs: Dict[str, float], bonuses: Dict[str, float]) -> None:
        # log per-prisoner payoffs and bonuses
        payoffs_log = {p: {"base": float(payoffs[p] - bonuses.get(p, 0)), "bonus": float(bonuses.get(p, 0)), "total": float(payoffs[p])} for p in self.prisoners}
        self.log_to_transcript({
            "round": self.round_number,
            "deliberation_turns": self.max_turns,
            "deliberation_log": self.deliberation_log.copy(),
            "final_actions": {k: v for k, v in actions.items()},
            "payoffs": payoffs_log,
            "cumulative_points": self.agent_points.copy()
        })

    def _build_step_info(self, actions: Dict[str, Dict[str, Any]], payoffs: Dict[str, float], bonuses: Dict[str, float]) -> Dict[str, Any]:
        return {
            "round": self.round_number,
            "round_cost": self.round_cost,
            "actions": {p: actions.get(p, {}).get("decision") for p in self.prisoners},
            "payoffs": {**{p: payoffs[p] for p in self.prisoners}, **{w: 0.0 for w in self.wardens}},
            "net_rewards": {p: payoffs[p] - self.round_cost for p in self.prisoners},
            "bonuses_applied": bonuses,
            "cumulative_points": self.agent_points.copy(),
        }

    def reset(self) -> Mapping[str, Dict[str, Any]]:
        self.round_number = 0
        self.interaction_count = 0
        self.turn_count = 0
        self._done = False
        self.current_turn_in_round = 0
        self.pending_decisions = {}
        self.deliberation_log = []
        self.agent_points = {role: self.starting_points for role in self.config.agent_roles if role not in self.wardens}
        self.last_round_outcome = None
        self.messages = {
            "private": { (sender, receiver): [] for sender in self.config.agent_roles for receiver in self.config.agent_roles if sender != receiver },
            "public": []
        }
        self.metrics = self._initialize_metrics()
        self.global_transcript = []
        self.current_interaction = self._generate_next_interaction()
        self.last_warden_advice = {
            w: {p: None for p in self.prisoners} for w in self.wardens
        }

        if self.current_interaction is None:
            raise RuntimeError("Environment generated None on first interaction.")

        return {
            agent_id: self._get_observation(self.current_interaction, agent_id)
            for agent_id in self.config.agent_roles
        }

    def _extract_private_message(self, private_messages_dict: Dict[str, Any], recipient: str) -> Optional[str]:
        if not isinstance(private_messages_dict, dict):
            return None
        msg = private_messages_dict.get(recipient)
        if msg and isinstance(msg, str) and msg.strip().lower() != "null":
            return msg
        return None