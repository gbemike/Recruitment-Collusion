"""LLM-backed agent implementations for social contagion."""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from llm_clients import GenerationResult, LLMClient, create_llm_client

from .base import AgentContext, BaseAgent
from .honest import HonestAgent
from .recruiter import RecruiterAgent

# Configure logging for parser
logger = logging.getLogger(__name__)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, int)):
        return f"{value}"
    return str(value)

@dataclass
class LLMMessageGenerator:
    """
    Utility that renders prompts and enforces strict JSON response formatting via config.
    """

    client: LLMClient
    scenario: str
    system_prompt: str = None
    user_template: str = None
    fallback_response: str = None
    stop_sequences: Sequence[str] = field(default_factory=tuple)
    default_temperature: float = None
    default_max_tokens: int = None
    response_format: Optional[Dict[str, Any]] = field(default=None)
    # _last_context: Mapping[str, str] | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_config(cls, scenario: str, config: Mapping[str, Any]) -> "LLMMessageGenerator":
        client = create_llm_client(config)
        system_prompt = config.get("system_prompt")
        user_template = config.get("user_prompt_template")
        fallback_response = config.get("fallback_response")
        stop_sequences = tuple(config.get("stop_sequences", []))
        temperature = config.get("temperature")
        max_tokens = config.get("max_tokens")
        response_format = config.get("response_format")

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

    def generate(self, observation: Mapping[str, Any], *, role: str) -> Dict[str, Any]:
        """Generate a response. Returns a dict with 'content', 'reasoning', 'usage'."""
        render_context = defaultdict(str)
        for key, value in observation.items():
            render_context[key] = _stringify(value)
        render_context["role"] = role
        render_context["scenario"] = self.scenario

        user_prompt = (self.user_template).format_map(render_context)
        # self._last_context = dict(render_context)

        extra: Dict[str, Any] = {}
        if self.system_prompt:
            extra["system_prompt"] = self.system_prompt
        if self.response_format:
            extra["response_format"] = self.response_format

        logger.debug(f"generate-start role={role} scenario={self.scenario}")

        gen_result: GenerationResult = self.client.generate(
            user_prompt,
            temperature=self.default_temperature,
            max_tokens=self.default_max_tokens,
            stop=self.stop_sequences,
            extra=extra if extra else None,
        )

        logger.debug(f"raw-response role={role}: {gen_result.content}")

        raw = gen_result.content
        if not raw or not raw.strip():
            logger.warning(f"Empty response from LLM for role={role}, using fallback")
            parsed_content = self._get_fallback()
        else:
            cleaned = self._postprocess(raw, role)
            parsed_content = cleaned if isinstance(cleaned, dict) else self._parse_json(cleaned, role)

        return {
            "content": parsed_content, # should always be dict
            "reasoning": gen_result.reasoning,
            "usage": gen_result.usage,
        }
    
    def _parse_json(self, text:str, role: str) -> Dict[str, Any]:
        if isinstance(text, dict):
            return text
        
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            logger.warning(f"[{role}] JSON parsed but not a dict: {type(result)}, returning empty dict")
            return self._get_fallback()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"[{role}] Failed to parse JSON into dict: {e}. Text: {text}")
            return self._get_fallback()        


    def _postprocess(self, text: str, role: str = "unknown") -> str:
        """
        Robustly extract a JSON object from raw LLM output.
        """
        if not text or not text.strip():
            logger.warning(f"[{role}] Empty/whitespace response, returning fallback")
            return self._get_fallback()

        # remove special characters
        sanitised = re.sub(r"\\[^\"\\\/bfnrtu]", "", text)
        sanitised = re.sub(r"\\\n", " ", sanitised)
        sanitised = re.sub(r"\\\r\n", " ", sanitised)
        sanitised = re.sub(r"\\\r", " ", sanitised)
        sanitised = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitised)
        sanitised = re.sub(r'(?<=[{,\[:])\s*\n\s*(?=")', "", sanitised)  # newline before a key
        sanitised = re.sub(r'"\s*\n\s*(?=[:{,\]}])', '"', sanitised)

        sanitised = sanitised.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        sanitised = re.sub(r"[\x00-\x1f\x7f]", "", sanitised)

        cleaned = sanitised.strip()

        # remove markdown fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        logger.debug(f"[{role}] Post-strip: {cleaned}")

        _, err = self._try_parse(cleaned)
        if err is None:
            logger.debug(f"[{role}] (regex extract) succeeded")
            return cleaned

        # regex, extract outermost brackets
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            logger.error(f"[{role}] No JSON object found. Raw: {text}")
            return cleaned

        candidate = match.group(0)
        logger.debug(f"[{role}] extracted ({len(candidate)} chars): {candidate}")

        _, err = self._try_parse(candidate)
        if err is None:
            logger.debug(f"[{role}](regex extract) succeeded")
            return candidate

        # count unmatched braces
        depth = 0
        in_string = False
        escape_next = False
        for ch in candidate:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
            if not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1

        logger.debug(f"[{role}] brace depth = {depth}")

        if depth == 0:
            # braces balanced but still failed
            logger.debug(f"[{role}] balanced fragment still failed: {err}")
            return candidate

        unescaped_quotes = len(re.findall(r'(?<!\\)"', candidate))
        if unescaped_quotes % 2 == 1:
            candidate += '"'
            logger.debug(f"[{role}] closed dangling string")

        # close missing braces
        candidate += "}" * depth
        logger.debug(f"[{role}] appended {depth} closing brace(s)")

        _, err = self._try_parse(candidate)
        if err is None:
            logger.debug(f"[{role}] (brace closure) succeeded")
            return candidate

        logger.debug(f"[{role}] failed: {err}")

        # trim trailing incomplete key-value pair after last comma
        last_comma = candidate.rfind(",")
        if last_comma > candidate.find("{"):
            trimmed = candidate[:last_comma] + "}" * depth
            _, err = self._try_parse(trimmed)
            if err is  None:
                logger.debug(f"[{role}] (comma-trim) succeeded")
                return trimmed
            logger.debug(f"[{role}] comma-trim failed: {err}")

        # trim trailing incomplete key (no colon after last comma)
        last_colon = candidate.rfind(":")
        if last_colon > candidate.find("{") and last_colon > last_comma if last_comma != -1 else True:
            trimmed = candidate[:last_colon].rstrip().rstrip(",").rstrip('"').rstrip()
            last_comma_before_key = trimmed.rfind(",")
            if last_comma_before_key > trimmed.find("{"):
                trimmed = trimmed[:last_comma_before_key] + "}" * depth
                _, err = self._try_parse(trimmed)
                if err is None:
                    logger.debug(f"[{role}] (key-trim) succeeded")
                    return trimmed
                logger.debug(f"[{role}] key-trim failed: {err}")

        logger.error(
            f"[{role}] All postprocess strategies failed.\n"
            f"  Original ({len(text)} chars): {text}\n"
            f"  Cleaned  ({len(cleaned)} chars): {cleaned}"
        )
        return cleaned or self._get_fallback()

    @staticmethod
    def _try_parse(text: str) -> tuple[Optional[Dict], Optional[str]]:
        """Attempt json.loads; return (dict, None) on success or (None, error_str) on failure."""
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result, None
            return None, f"parsed type={type(result).__name__} not dict"
        except (json.JSONDecodeError, ValueError) as e:
            return None, str(e)

    def _get_fallback(self) -> str:
        """Return fallback response if configured."""
        if self.fallback_response:
            return self.fallback_response
        return "{}"


class LLMHonestAgent(HonestAgent):
    """Honest agent backed by an LLM client."""

    def __init__(self, context: AgentContext, generator: LLMMessageGenerator) -> None:
        super().__init__(context)
        self.generator = generator
        self._last_reasoning: str = ""

    def act(self, observation: Mapping[str, Any]) -> Dict:
        result = self.generator.generate(observation, role=self.context.role)
        self._last_reasoning = result.get("reasoning", "")
        return result["content"]


class LLMRecruiterAgent(RecruiterAgent):
    """Recruiter agent backed by an LLM client."""

    def __init__(self, context: AgentContext, generator: LLMMessageGenerator) -> None:
        super().__init__(context)
        self.generator = generator
        self._last_reasoning: str = ""

    def act(self, observation: Mapping[str, Any]) -> Dict:
        result = self.generator.generate(observation, role=self.context.role)
        self._last_reasoning = result.get("reasoning", "")
        return result["content"]


def build_llm_agent(context: AgentContext, scenario: str, config: Mapping[str, Any]) -> BaseAgent:
    """Factory for LLM-backed agents using provided config."""
    generator = LLMMessageGenerator.from_config(scenario, config)
    
    if context.role == "recruiter" or context.recruiter:
        return LLMRecruiterAgent(context, generator)
    
    return LLMHonestAgent(context, generator)