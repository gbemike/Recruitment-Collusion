"""LLM client abstractions"""

from __future__ import annotations

import os

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
import logging
import random
import time
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Structured result from an LLM generation call."""
    content: str = ""
    reasoning: str = ""
    reasoning_details: List[Dict[str, Any]] = field(default_factory=list)
    has_reasoning: bool = False
    usage: Dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> GenerationResult:
        """Return a completion for the given prompt."""


class OpenRouterClient(LLMClient):
    """Wrapper around OpenRouter Chat Completions API."""

    BASE_URL = os.getenv("OPENROUTER_ENDPOINT")
    RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
        max_retries: int = 5,
        retry_base_wait: float = 2.0,
        retry_max_wait: float = 60.0,
        reasoning_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            import requests as _requests
        except ImportError as exc:
            raise RuntimeError(
                "OpenRouterClient requires the `requests` package."
                "Install it with `pip install requests`."
            ) from exc

        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "OpenRouterClient requires an API key via `api_key` or OPENROUTER_API_KEY."
            )

        self._headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.max_retries = max_retries
        self.retry_base_wait = retry_base_wait
        self.retry_max_wait = retry_max_wait
        self.reasoning_config = reasoning_config

    def _backoff_wait(self, attempt: int) -> float:
        wait = min(self.retry_base_wait * (2 ** (attempt - 1)), self.retry_max_wait)
        jitter = wait * 0.25 * random.random()
        return wait + jitter

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> GenerationResult:
        import requests as _requests

        empty_result = GenerationResult()

        messages = []
        if extra:
            system_prompt = extra.get("system_prompt")
            if system_prompt:
                messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        temp = temperature if temperature is not None else self.default_temperature
        if temp is not None:
            body["temperature"] = temp

        max_tok = max_tokens if max_tokens is not None else self.default_max_tokens
        if max_tok is not None:
            body["max_tokens"] = max_tok

        if stop:
            body["stop"] = list(stop)

        # reasoning_cfg = None
        # if extra and extra.get("reasoning"):
        #     reasoning_cfg = extra["reasoning"]
        # elif self.reasoning_config:
        #     reasoning_cfg = self.reasoning_config

        # if reasoning_cfg:
        #     if "effort" in reasoning_cfg:
        #         body["reasoning"] = {
        #             "effort": reasoning_cfg.get("effort", "medium")
        #         }

        if extra:
            response_format = extra.get("response_format")
            if response_format and isinstance(response_format, dict):
                fmt_type = response_format.get("type")
                if fmt_type == "json_schema":
                    body["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_format.get("name"),
                            "strict": True,
                            "schema": response_format.get("schema", {}),
                        },
                    }
                elif fmt_type == "json_object":
                    body["response_format"] = {"type": "json_object"}

        logger.info(f"[OpenRouterClient] Request model={self.model}, has_response_format={'response_format' in body}, has_reasoning={'reasoning' in body}")

        last_error: str = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = _requests.post(
                    self.BASE_URL,
                    headers=self._headers,
                    json=body,
                    timeout=120,
                )
            except _requests.RequestException as exc:
                logger.warning(
                    f"[OpenRouterClient] Attempt {attempt}/{self.max_retries}: network error: {exc}"
                )
                if attempt < self.max_retries:
                    wait = self._backoff_wait(attempt)
                    logger.info(f"[OpenRouterClient] Retrying in {wait:.1f}s...")
                    time.sleep(wait)
                    continue
                logger.error(f"[OpenRouterClient] Network error after {self.max_retries} attempts: {exc}")
                return empty_result

            if resp.status_code != 200:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", resp.text)
                except Exception:
                    error_msg = resp.text
                last_error = f"API error {resp.status_code}: {error_msg}"

                if resp.status_code in self.RETRIABLE_STATUS_CODES and attempt < self.max_retries:
                    wait = self._backoff_wait(attempt)
                    logger.warning(
                        f"[OpenRouterClient] Attempt {attempt}/{self.max_retries}: {last_error}. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    continue

                logger.error(f"[OpenRouterClient] {last_error}")
                return empty_result

            result = resp.json()

            usage = result.get("usage", {})
            if usage:
                logger.info(
                    f"[OpenRouterClient] Tokens: in={usage.get('prompt_tokens', '?')}, "
                    f"out={usage.get('completion_tokens', '?')}, "
                    f"total={usage.get('total_tokens', '?')}"
                )

            gen_result = self._extract_result(result)
            if gen_result.content:
                logger.debug(f"[OpenRouterClient] Response text: {gen_result.content[:500]}")
                if gen_result.has_reasoning:
                    logger.info(f"[OpenRouterClient] Reasoning extracted: {len(gen_result.reasoning)} chars, {len(gen_result.reasoning_details)} detail blocks")
            else:
                # empty response is retriable
                if attempt < self.max_retries:
                    wait = self._backoff_wait(attempt)
                    logger.warning(
                        f"[OpenRouterClient] Attempt {attempt}/{self.max_retries}: empty response. "
                        f"Retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    continue
                logger.warning(f"[OpenRouterClient] Empty response after {self.max_retries} attempts: {result}")
            return gen_result

        logger.error(f"[OpenRouterClient] All {self.max_retries} retries exhausted. Last error: {last_error}")
        return empty_result

    @staticmethod
    def _extract_result(result: Dict[str, Any]) -> GenerationResult:
        """Extract generated text and reasoning from Chat Completions response."""
        choices = result.get("choices", [])
        if not choices:
            return GenerationResult(usage=result.get("usage", {}))

        message = choices[0].get("message", {})
        content = (message.get("content") or "").strip()

        raw_reasoning = (message.get("reasoning") or "").strip()
        reasoning_details = message.get("reasoning_details") or []

        if isinstance(reasoning_details, str):
            reasoning_details = [{"type": "reasoning.text", "text": reasoning_details}]
        elif not isinstance(reasoning_details, list):
            reasoning_details = []

        has_reasoning = bool(raw_reasoning or reasoning_details)

        # if we have reasoning_details but no raw_reasoning, build raw_reasoning from details
        if not raw_reasoning and reasoning_details:
            parts = []
            for detail in reasoning_details:
                if isinstance(detail, dict):
                    if detail.get("type") == "reasoning.text" and detail.get("text"):
                        parts.append(detail["text"])
                    elif detail.get("type") == "reasoning.summary" and detail.get("summary"):
                        parts.append(f"[Summary] {detail['summary']}")
                    elif detail.get("type") == "reasoning.encrypted":
                        parts.append("[Encrypted reasoning block]")
                elif isinstance(detail, str):
                    parts.append(detail)
            raw_reasoning = "\n".join(parts)

        return GenerationResult(
            content=content,
            reasoning=raw_reasoning,
            reasoning_details=reasoning_details,
            has_reasoning=has_reasoning,
            usage=result.get("usage", {}),
        )


def create_llm_client(config: Mapping[str, Any]) -> LLMClient:
    """Instantiate an LLM client from configuration."""

    backend = config.get("backend")
    if not backend:
        raise ValueError("LLM configuration must include a 'backend' field.")

    backend = backend.lower()

    if backend in {"openrouter"}:
        return OpenRouterClient(
            model=config["model"],
            api_key=config.get("api_key"),
            default_temperature=config.get("temperature"),
            default_max_tokens=config.get("max_tokens"),
            reasoning_config=config.get("reasoning"),
        )

    raise ValueError(f"Unsupported LLM backend '{backend}'.")