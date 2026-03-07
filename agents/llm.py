"""LLM-backed agent implementations for social contagion."""

from __future__ import annotations

import importlib
import os
import re
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .base import AgentContext, BaseAgent
from .recruiter import RecruiterAgent
from .honest import HonestAgent
from llm_clients import LLMClient, create_llm_client

# Configure logging for parser
logger = logging.getLogger(__name__)


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
    system_prompt: str | None = None
    user_template: str | None = None
    fallback_response: Dict | None = None
    stop_sequences: Sequence[str] = field(default_factory=tuple)
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    response_format: Optional[Dict[str, Any]] = field(default=None)
    _last_context: Mapping[str, str] | None = field(default=None, init=False, repr=False)
    debug: bool = field(default_factory=_debug_enabled, init=False, repr=False)

    @classmethod
    def from_config(cls, scenario: str, config: Mapping[str, Any]) -> "LLMMessageGenerator":
        client = create_llm_client(config)
        system_prompt = config.get("system_prompt")
        user_template = config.get("user_prompt_template")

        fallback_response = config.get("fallback_response")
        stop_sequences = tuple(config.get("stop_sequences", []))
        temperature = config.get("temperature")
        max_tokens = config.get("max_tokens")

        # structured output schema
        response_format = config.get("response_format")

        tool_fns: Dict[str, Callable[[Mapping[str, Any]], Any]] = {}
        tools_cfg = config.get("tools", {})
        for name, path in tools_cfg.items():
            tool_fns[name] = _load_tool(path)

        return cls(
            client=client,
            scenario=scenario,
            system_prompt=system_prompt,
            user_template=user_template,
            fallback_response=fallback_response,
            stop_sequences=stop_sequences,
            default_temperature=temperature,
            default_max_tokens=max_tokens,
            response_format=response_format,
        )

    def generate(self, observation: Mapping[str, Any], *, role: str) -> str:
        render_context = defaultdict(str)
        for key, value in observation.items():
            render_context[key] = _stringify(value)
        render_context["role"] = role
        render_context["scenario"] = self.scenario

        user_prompt = (self.user_template).format_map(render_context)
        self._last_context = dict(render_context)

        extra = {
            "system_prompt": self.system_prompt,
            # "variables": render_context,
        }
        if self.response_format:
            extra["response_format"] = self.response_format

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
        return response

    def _postprocess(self, text: str) -> str:
        """Extract JSON from LLM response, handling truncation."""
        if not text or not text.strip():
            logger.warning("Empty or whitespace-only response received, returning fallback")
            return self._get_fallback()

        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            json.loads(cleaned)
            logger.debug(f"Successfully parsed cleaned response: {cleaned[:200]}")
            return cleaned
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Initial JSON parse failed: {e}, attempting extraction")

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                json.loads(candidate)
                logger.debug(f"Successfully parsed regex-extracted JSON: {candidate[:200]}")
                return candidate
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug(f"Regex-extracted candidate failed: {e}")

        brace_idx = cleaned.find("{")
        if brace_idx != -1:
            fragment = cleaned[brace_idx:]
            logger.debug(f"Attempting brace recovery from index {brace_idx}. Fragment: {fragment[:300]}")
            depth = 0
            for ch in fragment:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
            if depth > 0:
                fragment = fragment.rstrip()
                if fragment.count('"') % 2 == 1:
                    fragment += '"'
                fragment += "}" * depth
                try:
                    json.loads(fragment)
                    logger.debug(f"Successfully recovered truncated JSON: {fragment[:200]}")
                    return fragment
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"Truncated JSON recovery failed: {e}, attempting comma-trim")
                    last_comma = fragment.rfind(",")
                    last_colon = fragment.rfind(":")
                    if last_comma > 0 and last_comma > fragment.find("{"):
                        trimmed = fragment[:last_comma] + "}" * depth
                        try:
                            json.loads(trimmed)
                            logger.debug(f"Successfully recovered after comma-trim: {trimmed[:200]}")
                            return trimmed
                        except (json.JSONDecodeError, ValueError) as e:
                            logger.warning(f"Comma-trim recovery failed: {e}")

        logger.error(f"All parsing strategies failed. Original text: {text[:500]}. Cleaned: {cleaned[:500]}")
        return cleaned or self._get_fallback()

    def _get_fallback(self) -> str:
        """Return fallback response if configured."""
        if self.fallback_response:
            return self.fallback_response
        return {}


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