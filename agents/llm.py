"""LLM-backed agent implementations for social contagion."""

from __future__ import annotations

import importlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .base import AgentContext, BaseAgent
from .recruiter import RecruiterAgent
from .honest import HonestAgent
from llm_clients import LLMClient, create_llm_client


def _debug_enabled() -> bool:
    value = os.getenv("RECRUITBENCH_DEBUG_LLMS", "").strip().lower()
    if not value:
        return False
    return value in {"1", "true", "yes", "on"}


def _debug_print(*parts: object) -> None:
    if _debug_enabled():
        print("[LLMDebug]", *parts)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, int)):
        return f"{value}"
    return str(value)


def _load_tool(function_path: str) -> Callable[[Mapping[str, Any]], Any]:
    module_name, attr = function_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, attr)
    if not callable(func):
        raise TypeError(f"Configured tool '{function_path}' is not callable.")
    return func


@dataclass
class LLMMessageGenerator:
    """
    Utility that renders prompts and enforces strict JSON response formatting via config.
    """

    client: LLMClient
    scenario: str
    system_prompt: str | None = None # for specific task
    user_template: str | None = None
    response_regex: re.Pattern[str] | None = None
    response_template: str | None = None
    fallback_response: str | None = None
    stop_sequences: Sequence[str] = field(default_factory=tuple)
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    tool_functions: Dict[str, Callable[[Mapping[str, Any]], Any]] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=lambda: {"history": []})
    _last_context: Mapping[str, str] | None = field(default=None, init=False, repr=False)
    debug: bool = field(default_factory=_debug_enabled, init=False, repr=False)

    @classmethod
    def from_config(cls, scenario: str, config: Mapping[str, Any]) -> "LLMMessageGenerator":
        client = create_llm_client(config)
        system_prompt = config.get("system_prompt")
        user_template = config.get("user_prompt_template")

        # Default regex searches for JSON objects if none provided
        pattern = config.get("response_regex", r"(\{.*\})")
        response_regex = re.compile(pattern, flags=re.MULTILINE | re.DOTALL)

        response_template = config.get("response_template")
        fallback_response = config.get("fallback_response")
        stop_sequences = tuple(config.get("stop_sequences", []))
        temperature = config.get("temperature")
        max_tokens = config.get("max_tokens")

        tool_fns: Dict[str, Callable[[Mapping[str, Any]], Any]] = {}
        tools_cfg = config.get("tools", {})
        for name, path in tools_cfg.items():
            tool_fns[name] = _load_tool(path)

        return cls(
            client=client,
            scenario=scenario,
            system_prompt=system_prompt,
            user_template=user_template,
            response_regex=response_regex,
            response_template=response_template,
            fallback_response=fallback_response,
            stop_sequences=stop_sequences,
            default_temperature=temperature,
            default_max_tokens=max_tokens,
            tool_functions=tool_fns,
        )

    def generate(self, observation: Mapping[str, Any], *, role: str) -> str:
        render_context = defaultdict(str)
        for key, value in observation.items():
            render_context[key] = _stringify(value)
        render_context["role"] = role
        render_context["scenario"] = self.scenario

        tools_payload: Dict[str, Any] = {}
        if self.tool_functions:
            tool_context = {
                "role": role,
                "scenario": self.scenario,
                "observation": observation,
                "state": self.state,
            }
            for name, func in self.tool_functions.items():
                try:
                    tools_payload[name] = func(tool_context)
                except Exception as exc:
                    tools_payload[name] = f"[tool-error:{exc}]"
            render_context.update({k: _stringify(v) for k, v in tools_payload.items()})

        user_prompt = (self.user_template or "{observation}").format_map(render_context)
        self._last_context = dict(render_context)

        extra = {
            "system_prompt": self.system_prompt,
            "variables": render_context,
            "tools": tools_payload,
        }

        if self.debug:
            _debug_print(f"generate-start role={role} scenario={self.scenario}")

        raw = self.client.generate(
            user_prompt,
            temperature=self.default_temperature,
            max_tokens=self.default_max_tokens,
            stop=self.stop_sequences,
            extra=extra,
        )

        if self.debug:
            _debug_print(f"raw-response role={role}", raw)

        response = self._postprocess(raw)
        self.state.setdefault("history", []).append({"observation": observation, "response": response})
        return response

    def _postprocess(self, text: str) -> str:
        """
        Extracts JSON via regex and optionally wraps it in a response template.
        """
        extracted_value: Optional[str] = None
        
        if self.response_regex:
            match = self.response_regex.search(text)
            if match:
                extracted_value = match.group(1) if match.groups() else match.group(0)
        
        if not extracted_value and text.strip().startswith("{"):
            extracted_value = text.strip()

        if extracted_value and self.response_template:
            try:
                sanitized = self.response_template.format(value=extracted_value)
            except (KeyError, ValueError):
                sanitized = extracted_value
        else:
            sanitized = extracted_value or text.strip()

        if not sanitized and self.fallback_response:
            context = self._last_context or defaultdict(str)
            sanitized = self.fallback_response.format_map(context).strip()

        return sanitized


class LLMHonestAgent(BaseAgent):
    """Honest agent backed by an LLM client."""

    def __init__(self, context: AgentContext, generator: LLMMessageGenerator) -> None:
        super().__init__(context)
        self.generator = generator

    def act(self, observation: Mapping[str, Any]) -> str:
        return self.generator.generate(observation, role=self.context.role)


class LLMRecruiterAgent(BaseAgent):
    """Recruiter agent backed by an LLM client."""

    def __init__(self, context: AgentContext, generator: LLMMessageGenerator) -> None:
        super().__init__(context)
        self.generator = generator

    def act(self, observation: Mapping[str, Any]) -> str:
        return self.generator.generate(observation, role=self.context.role)


def build_llm_agent(context: AgentContext, scenario: str, config: Mapping[str, Any]) -> BaseAgent:
    """Factory for LLM-backed agents using provided config."""
    generator = LLMMessageGenerator.from_config(scenario, config)
    
    if context.role == "recruiter" or context.recruiter:
        return LLMRecruiterAgent(context, generator)
    
    return LLMHonestAgent(context, generator)