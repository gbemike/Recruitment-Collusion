"""Configuration schema definitions for social dilemma experiments."""

from __future__ import annotations

import re
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _BaseStrictModel(BaseModel):
	model_config = ConfigDict(extra='forbid', populate_by_name=True)


class ReasoningConfig(BaseModel):
	effort: Optional[Literal['low', 'medium', 'high']]
	max_tokens: Optional[int]


class StringAdditionalProperties(_BaseStrictModel):
	type: Literal['string']


class BooleanAdditionalProperties(_BaseStrictModel):
	type: Literal['boolean']


class AdviceAdditionalProperties(_BaseStrictModel):
	type: Literal['string']
	enum: list[Literal['cooperate', 'defect']]


class PrivateMessagesProperty(_BaseStrictModel):
	type: Literal['object']
	description: str
	additionalProperties: StringAdditionalProperties


class RecruitedAgentsProperty(_BaseStrictModel):
	type: Literal['object']
	description: str
	additionalProperties: BooleanAdditionalProperties


class WardenAdviceProperty(_BaseStrictModel):
	type: Literal['object']
	description: str
	additionalProperties: AdviceAdditionalProperties


class ReasoningProperty(_BaseStrictModel):
	type: Literal['string']
	description: str


class PrisonerDecisionProperty(_BaseStrictModel):
	type: Literal['string']
	enum: List[Literal['cooperate', 'defect']]
	description: str


class WardenSchemaProperties(_BaseStrictModel):
	private_messages: PrivateMessagesProperty
	recruited_agents: RecruitedAgentsProperty
	warden_advice: WardenAdviceProperty
	reasoning: ReasoningProperty


class WardenActionSchema(_BaseStrictModel):
	type: Literal['object']
	properties: WardenSchemaProperties
	required: List[Literal['private_messages', 'recruited_agents', 'warden_advice', 'reasoning']]
	additionalProperties: Literal[False]


class WardenResponseFormat(_BaseStrictModel):
	type: str
	name: str
	json_schema: WardenActionSchema = Field(alias='schema')


class WardenFallbackResponse(_BaseStrictModel):
	private_messages: Union[str, Dict]
	recruited_agents: Union[str, Dict]
	warden_advice: Union[str, Dict]
	reasoning: Optional[str]


class PrisonerSchemaProperties(_BaseStrictModel):
	decision: PrisonerDecisionProperty
	public_message: ReasoningProperty
	private_messages: PrivateMessagesProperty
	reasoning: ReasoningProperty


class PrisonerActionSchema(_BaseStrictModel):
	type: Literal['object']
	properties: PrisonerSchemaProperties
	required: List[Literal['decision', 'public_message', 'private_messages', 'reasoning']]
	additionalProperties: Literal[False]


class PrisonerResponseFormat(_BaseStrictModel):
	type: str
	name: str
	json_schema: PrisonerActionSchema = Field(alias='schema')


class PrisonerFallbackResponse(_BaseStrictModel):
	decision: Optional[str]
	public_message: Optional[str]
	private_messages: Union[str, Dict]
	reasoning: Optional[str]


class WardenConfig(BaseModel):
	model: str
	temperature: Annotated[float, Field(gt=0, le=2)]
	max_tokens: int
	reasoning: ReasoningConfig
	response_format: WardenResponseFormat
	system_prompt: str
	user_prompt_template: str


class PrisonerConfig(BaseModel):
	model: str
	temperature: Annotated[float, Field(gt=0, le=2)]
	max_tokens: int
	reasoning: ReasoningConfig
	response_format: PrisonerResponseFormat
	system_prompt: str
	user_prompt_template: str


class EnvParams(BaseModel):
	payoff_matrix: Dict[str, List[int]]
	starting_points: int
	round_cost: int
	warden_bonus: int

	@field_validator('payoff_matrix')
	@classmethod
	def validate_payoff_matrix(cls, v):
		if not isinstance(v, dict):
			raise TypeError("payoff_matrix must be a mapping of 'action1,action2,...' -> [int,...]")

		key_pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(,[A-Za-z_][A-Za-z0-9_]*)*$')
		allowed_actions = ['cooperate', 'defect']

		for key in v.keys():
			if not isinstance(key, str) or not key_pattern.fullmatch(key):
				raise ValueError(
					f'Invalid payoff_matrix kay: {key}. Keys must be comma-separated with no spaces'
				)
			tokens = key.split(',')
			for t in tokens:
				if t not in allowed_actions:
					raise ValueError(
						f"Invalid action token '{t}' in payoff key '{key}'. Allowed actions: {allowed_actions}"
					)

		return v


class ConfigPath(BaseModel):
	agent_names: List[str]
	recruiters: List[str]
	honest_agents: List[str]
	max_interactions: int
	max_turns_per_interaction: int
	env_params: EnvParams
	llm_agents: Dict[
		str,
		Union[
			WardenConfig,
			PrisonerConfig,
			WardenFallbackResponse,
			PrisonerFallbackResponse,
		],
	]

	@field_validator('llm_agents')
	@classmethod
	def validate_llm_agent_names(cls, value):
		pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
		invalid_names = [k for k in value.keys() if not pattern.fullmatch(k)]
		if invalid_names:
			raise ValueError(
				f'Invalid LLM agent names/keys: {", ".join(invalid_names)},  Names must match pattern ^[A-Za-z_][A-Za-z0-9_]*$ (no spaces)'
			)
		return value

	@field_validator('recruiters', 'honest_agents', 'agent_names')
	@classmethod
	def validate_agent_name_lists(cls, value):
		pattern = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
		invalid_names = [v for v in value if not pattern.fullmatch(v)]
		if invalid_names:
			raise ValueError(
				f'Invalid LLM agent names/keys: {", ".join(invalid_names)},  Names must match pattern ^[A-Za-z_][A-Za-z0-9_]*$ (no spaces)'
			)
		return value

	@model_validator(mode='after')
	def validate_payoff_consistency(self) -> ConfigPath:
		n = len(self.honest_agents)
		if n <= 0:
			raise ValueError('Could not infer any prisoners from `honest_agents`.')

		# validate decisions count in key
		pm = self.env_params.payoff_matrix
		for key in pm.keys():
			parts = [k.strip() for k in key.split(',')]
			if len(parts) != n:
				raise ValueError(
					f"Key '{key}' has {len(parts)} action(s); expected {n} (one per prisoner)."
				)

		# each payoff list length must equal prisoners_count
		for key, val in pm.items():
			if len(val) != n:
				raise ValueError(
					f"Payoff list for '{key}' has length {len(val)}; expected {n} (one payoff per prisoner)."
				)

		# validate payoff matrix key count
		expected_keys = 2**n
		if len(pm) != expected_keys:
			raise ValueError(
				f'payoff_matrix must contain {expected_keys} entries for {n} prisoners'
			)

		return self
