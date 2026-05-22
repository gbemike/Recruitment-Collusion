from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Mapping, Optional

COOPERATE = 'cooperate'
DEFECT = 'defect'


def build_round_payoff_breakdown_history(
	past_round_payoff_breakdowns: Dict[int, Dict[str, Dict[str, float]]],
):
	history = []
	for round_num in sorted(past_round_payoff_breakdowns.keys()):
		history.append(
			{
				'round': round_num,
				'payoff_breakdown': copy.deepcopy(past_round_payoff_breakdowns[round_num]),
			}
		)
	return history


def build_round_recruitment_results_history(
	past_round_recruitment_results: Dict[int, Dict[str, Dict[str, Any]]],
):
	history = []
	for round_num in sorted(past_round_recruitment_results.keys()):
		history.append(
			{
				'round': round_num,
				'recruitment_results': copy.deepcopy(past_round_recruitment_results[round_num]),
			}
		)
	return history


def build_prisoner_decision_history(env, prisoner_id: str) -> List[Dict[str, Any]]:
	history: List[Dict[str, Any]] = []

	# include every turn from completed rounds first
	for round_num in sorted(env.past_round_deliberation_logs.keys()):
		for entry in env.past_round_deliberation_logs[round_num]:
			turn_entry = {
				'round': round_num,
				'turn': entry['turn'],
				'your_decision': entry.get('agent_decisions', {}).get(prisoner_id),
				'warden_advice': {},
			}
			for warden_id, advice_dict in entry.get('warden_advice', {}).items():
				if isinstance(advice_dict, dict):
					turn_entry['warden_advice'][warden_id] = advice_dict.get(prisoner_id)
				else:
					turn_entry['warden_advice'][warden_id] = advice_dict
			history.append(turn_entry)

	# then append the in-progress current round turn-by-turn trace
	for entry in env.deliberation_log:
		turn_entry = {
			'round': env.round_number,
			'turn': entry['turn'],
			'your_decision': entry.get('agent_decisions', {}).get(prisoner_id),
			'warden_advice': {},
		}
		for warden_id, advice_dict in entry.get('warden_advice', {}).items():
			if isinstance(advice_dict, dict):
				turn_entry['warden_advice'][warden_id] = advice_dict.get(prisoner_id)
			else:
				turn_entry['warden_advice'][warden_id] = advice_dict
		history.append(turn_entry)

	return history


def build_all_prisoners_decision_history(env) -> Dict[str, List[Dict[str, Any]]]:
	return {
		prisoner_id: build_prisoner_decision_history(env, prisoner_id)
		for prisoner_id in env.prisoners
	}


def format_outcome_for_agent(
	outcome: Optional[Dict[str, str]], agent_id: str
) -> Optional[Dict[str, Any]]:
	if outcome is None:
		return None
	your_action = outcome.get(agent_id)
	others_actions = [a for p, a in outcome.items() if p != agent_id]
	return {'your_action': your_action, 'others_actions': others_actions}


def extract_private_message(private_messages_dict: Dict[str, Any], recipient: str) -> Optional[str]:
	if not isinstance(private_messages_dict, dict):
		return None
	msg = private_messages_dict.get(recipient)
	if msg and isinstance(msg, str) and msg.strip().lower() != 'null':
		return msg
	return None


def parse_prisoner_action(
	agent_actions: Mapping[str, Any], agent_id: str, wardens: List[str], logger: Any
) -> Dict[str, Any]:
	if agent_id not in agent_actions:
		logger.debug(f'[{agent_id}] No action provided')
		return {}
	action = agent_actions[agent_id]

	logger.debug(
		f'[{agent_id}] Raw action received: type={type(action).__name__}, preview={str(action)[:300]}'
	)

	if isinstance(action, str):
		logger.debug(
			f'[{agent_id}] Still string after processing, attempting final parse: {action[:300]}'
		)
		try:
			parsed = json.loads(action)
			if isinstance(parsed, dict):
				action = parsed
		except (json.JSONDecodeError, ValueError) as e:
			logger.error(f'[{agent_id}] Final JSON parse failed: {e}, action={str(action)[:300]}')

	decision = None
	public_message = None
	reasoning = None
	private_messages: Dict[str, Any] = {}

	if isinstance(action, dict):
		decision = action.get('decision')
		if isinstance(decision, str):
			decision = decision.strip().lower()

		public_message = action.get('public_message')

		raw_pm = action.get('private_messages', action.get('private_message'))
		if isinstance(raw_pm, dict):
			private_messages = raw_pm
		elif isinstance(raw_pm, str):
			s = raw_pm.strip()
			if s and s.lower() != 'null':
				if wardens:
					private_messages = {wardens[0]: s}
			else:
				private_messages = {}
		else:
			private_messages = {}

		reasoning = action.get('reasoning')

	else:
		logger.warning(
			f'Unparseable action for {agent_id}; using safe default. preview={str(action)[:200]}'
		)
		return {
			'decision': None,
			'public_message': None,
			'private_messages': {},
			'reasoning': None,
		}

	if decision not in [COOPERATE, DEFECT, None]:
		logger.warning(
			f'Invalid decision for {agent_id}, defaulting to cooperate. Got type={type(action).__name__}, value={decision}, full_action={str(action)[:200]}'
		)
		decision = COOPERATE

	logger.debug(
		f'[{agent_id}] Parsed action: decision={decision}, has_reasoning={reasoning is not None}, num_private_messages={len(private_messages)}'
	)

	return {
		'decision': decision,
		'public_message': public_message,
		'private_messages': private_messages,
		'reasoning': reasoning,
	}


def parse_warden_action(
	agent_actions: Mapping[str, Any], agent_id: str, prisoners: List[str], logger: Any
) -> Dict[str, Any]:
	default_action = {'reasoning': None}

	if agent_id not in agent_actions:
		logger.debug(f'[{agent_id}] No action provided')
		return default_action

	action = agent_actions[agent_id]
	logger.debug(
		f'[{agent_id}] Raw warden action received: type={type(action).__name__}, preview={str(action)[:300]}'
	)

	if isinstance(action, str):
		try:
			parsed = json.loads(action)
			if isinstance(parsed, dict):
				logger.debug(f'[{agent_id}] Successfully parsed string action')
				action = parsed
		except (json.JSONDecodeError, ValueError) as e:
			logger.warning(f'[{agent_id}] JSON parse failed: {e}, action={str(action)[:300]}')

	if not isinstance(action, dict):
		logger.error(
			f'Warden action unparseable for {agent_id}, using defaults. type={type(action).__name__}, preview={str(action)[:150]}'
		)
		return default_action

	raw_pm = action.get('private_messages', action.get('private_message'))
	if isinstance(raw_pm, dict):
		private_messages = raw_pm
	elif isinstance(raw_pm, str):
		s = raw_pm.strip()
		if s and s.lower() != 'null':
			private_messages = {p: s for p in prisoners}
		else:
			private_messages = {}
	else:
		private_messages = {}

	recruited_agents = action.get('recruited_agents')
	if not isinstance(recruited_agents, dict):
		recruited_agents = {}

	raw_advice = action.get('warden_advice', {})
	warden_advice: Dict[str, Optional[str]] = {}
	if isinstance(raw_advice, dict):
		for pid, adv in raw_advice.items():
			if isinstance(adv, str) and adv.strip().lower() in (COOPERATE, DEFECT):
				warden_advice[pid] = adv.strip().lower()
			else:
				warden_advice[pid] = None

	reasoning = action.get('reasoning')

	logger.debug(
		f'[{agent_id}] Parsed warden action: has_reasoning={reasoning is not None}, num_private_messages={len(private_messages)}, recruited_count={len(recruited_agents)}, advice={warden_advice}'
	)

	return {
		'private_messages': private_messages,
		'recruited_agents': recruited_agents,
		'warden_advice': warden_advice,
		'reasoning': reasoning,
	}


def build_step_info(
	round_number: int,
	round_cost: float,
	prisoners: List[str],
	wardens: List[str],
	actions: Dict[str, Dict[str, Any]],
	payoffs: Dict[str, float],
	bonuses: Dict[str, float],
	cumulative_points: Dict[str, float],
) -> Dict[str, Any]:
	return {
		'round': round_number,
		'round_cost': round_cost,
		'actions': {p: actions.get(p, {}).get('decision') for p in prisoners},
		'payoffs': {
			**{p: payoffs[p] for p in prisoners},
			**{w: 0.0 for w in wardens},
		},
		'net_rewards': {p: payoffs[p] - round_cost for p in prisoners},
		'bonuses_applied': bonuses,
		'cumulative_points': cumulative_points.copy(),
	}
