"""LLM client abstractions"""

from __future__ import annotations

import os

os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
import time
from dotenv import load_dotenv

load_dotenv()


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
    ) -> str:
        """Return a completion for the given prompt."""


class OpenAIChatClient(LLMClient):
    """Wrapper around the OpenAI Chat Completions API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - missing optional dependency
            raise RuntimeError(
                "OpenAIChatClient requires the `openai` package. "
                "Install it with `pip install openai`."
            ) from exc

        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OpenAIChatClient requires an API key via `api_key` or OPENAI_API_KEY.")

        self._client = OpenAI(api_key=api_key, base_url=base_url or os.getenv("OPENAI_BASE_URL"))
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        messages = []
        if extra:
            system_prompt = extra.get("system_prompt")
            if system_prompt:
                messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.default_temperature,
            max_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
            stop=stop,
        )
        return response.choices[0].message.content.strip()


class TransformersClient(LLMClient):
    """Wrapper around Hugging Face transformers pipelines."""

    def __init__(
        self,
        model: str,
        *,
        device: Optional[str | int] = None,
        max_new_tokens: int = 128,
        default_temperature: Optional[float] = None,
        pipeline_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> None:
        try:
            from transformers import pipeline  # type: ignore
        except ImportError as exc:  # pragma: no cover - missing optional dependency
            raise RuntimeError(
                "TransformersClient requires the `transformers` package. "
                "Install it with `pip install transformers accelerate`."
            ) from exc

        kwargs = dict(pipeline_kwargs or {})
        task = kwargs.pop("task", "text-generation")
        self._generator = pipeline(task, model=model, device=device, **kwargs)
        tokenizer = getattr(self._generator, "tokenizer", None)
        if tokenizer is not None and tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token  # type: ignore[attr-defined]

        self.max_new_tokens = max_new_tokens
        self.default_temperature = default_temperature

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        generation_kwargs: Dict[str, Any] = {
            "max_new_tokens": max_tokens if max_tokens is not None else self.max_new_tokens,
        }
        if temperature is not None or self.default_temperature is not None:
            generation_kwargs["temperature"] = temperature if temperature is not None else self.default_temperature
        outputs = self._generator(prompt, **generation_kwargs)
        text = outputs[0]["generated_text"]
        if stop:
            for token in stop:
                if token in text:
                    text = text.split(token)[0]
                    break
        return text.strip()


class GeminiClient(LLMClient):
    """Wrapper around Google Gemini (Generative AI) API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
    ) -> None:
        try:
            from google import genai
            from google.api_core.exceptions import ResourceExhausted, InvalidArgument  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "GeminiClient requires the `google-genai` package. "
                "Install it with `pip install google-genai`."
            ) from exc

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GeminiClient requires an API key via GOOGLE_API_KEY or GEMINI_API_KEY.")

        self.client = genai.Client(api_key=api_key)
        self._model_name = model
        self._ResourceExhausted = ResourceExhausted
        self._InvalidArgument = InvalidArgument
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        from google.genai import types

        config: Dict[str, Any] = {}
        if temperature is not None or self.default_temperature is not None:
            config["temperature"] = temperature if temperature is not None else self.default_temperature
        if max_tokens is not None or self.default_max_tokens is not None:
            config["max_output_tokens"] = max_tokens if max_tokens is not None else self.default_max_tokens
        if stop:
            config["stop_sequences"] = list(stop)

        system_instruction = None
        if extra:
            sp = extra.get("system_prompt")
            if sp:
                system_instruction = str(sp)
            # Structured output support
            response_format = extra.get("response_format")
            if response_format:
                config["response_mime_type"] = "application/json"
                if isinstance(response_format, dict) and "schema" in response_format:
                    config["response_schema"] = response_format["schema"]

        try:
            gen_config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                **config,
            ) if (config or system_instruction) else None

            response = self.client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=gen_config,
            )
        except (self._ResourceExhausted, self._InvalidArgument) as exc:
            print(f"[GeminiClient] Gemini API request failed: {exc}")
            return ""
        except Exception as exc:
            print(f"[GeminiClient] Unexpected Gemini error: {exc}")
            raise

        text: str = ""
        try:
            if hasattr(response, "text") and response.text:
                text = response.text.strip()
        except ValueError as exc:
            print(f"[GeminiClient] Failed to parse Gemini response text: {exc}")

        if not text:
            parts: list[str] = []
            for candidate in getattr(response, "candidates", []) or []:
                finish_reason = getattr(candidate, "finish_reason", None)
                if finish_reason and str(finish_reason).lower() != "finish_reason.stop":
                    print(f"[GeminiClient] Skipping candidate due to finish reason: {finish_reason}")
                    continue
                for part in getattr(candidate, "content", {}).get("parts", []):
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
            text = "\n".join(parts).strip()

        if text:
            print(f"[GeminiClient] Response text: {text}")
        else:
            print(f"[GeminiClient] Gemini response contained no text: {response}")
        return text


class OpenRouterClient(LLMClient):
    """Wrapper around OpenRouter Chat Completions API."""

    BASE_URL = os.getenv("OPENROUTER_ENDPOINT")

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
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

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        import requests as _requests

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

        print(f"[OpenRouterClient] Request model={self.model}, has_response_format={'response_format' in body}")

        try:
            resp = _requests.post(
                self.BASE_URL,
                headers=self._headers,
                json=body,
                timeout=120,
            )
        except _requests.RequestException as exc:
            print(f"[OpenRouterClient] Network error: {exc}")
            return ""

        if resp.status_code != 200:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text
            print(f"[OpenRouterClient] API error {resp.status_code}: {error_msg}")
            return ""

        result = resp.json()

        usage = result.get("usage", {})
        if usage:
            print(
                f"[OpenRouterClient] Tokens: in={usage.get('prompt_tokens', '?')}, "
                f"out={usage.get('completion_tokens', '?')}, "
                f"total={usage.get('total_tokens', '?')}"
            )

        text = self._extract_text(result)
        if text:
            print(f"[OpenRouterClient] Response text: {text[:500]}")
        else:
            print(f"[OpenRouterClient] Empty response: {result}")
        return text

    @staticmethod
    def _extract_text(result: Dict[str, Any]) -> str:
        """Extract generated text from Chat Completions response."""
        choices = result.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if content:
                return content.strip()
        return ""


class TemplateClient(LLMClient):
    """Deterministic template-based client for offline tests."""

    def __init__(self, template: str) -> None:
        self.template = template

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        variables = extra.get("variables", {}) if extra else {}
        return self.template.format_map(_SafeDefaultDict(variables)).strip()


class RateLimitedClient(LLMClient):
    """Wrapper that enforces a minimum interval between API calls."""

    def __init__(self, base: LLMClient, min_interval: float) -> None:
        self._base = base
        self._min_interval = max(min_interval, 0.0)
        self._lock = Lock()
        self._last_request = 0.0

    def generate(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> str:
        with self._lock:
            if self._min_interval > 0:
                now = time.time()
                wait = self._min_interval - (now - self._last_request)
                if wait > 0:
                    time.sleep(wait)
            result = self._base.generate(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                extra=extra,
            )
            self._last_request = time.time()
            return result


def create_llm_client(config: Mapping[str, Any]) -> LLMClient:
    """Instantiate an LLM client from configuration."""

    backend = config.get("backend")
    if not backend:
        raise ValueError("LLM configuration must include a 'backend' field.")

    backend = backend.lower()
    if backend in {"openai", "openai_chat"}:
        return OpenAIChatClient(
            model=config["model"],
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            default_temperature=config.get("temperature"),
            default_max_tokens=config.get("max_tokens"),
        )
    if backend in {"groq"}:
        api_key = config.get("api_key")
        if not api_key:
            api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("Groq backend requires an API key via `api_key` or GROQ_API_KEY.")
        base_url = config.get("base_url", "https://api.groq.com/openai/v1")
        min_interval = float(config.get("min_request_interval", os.getenv("GROQ_MIN_REQUEST_INTERVAL", 2.1)))
        client = OpenAIChatClient(
            model=config["model"],
            api_key=api_key,
            base_url=base_url,
            default_temperature=config.get("temperature"),
            default_max_tokens=config.get("max_tokens"),
        )
        if min_interval > 0:
            return RateLimitedClient(client, min_interval)
        return client
    if backend in {"hf", "transformers", "huggingface"}:
        return TransformersClient(
            model=config["model"],
            device=config.get("device"),
            max_new_tokens=config.get("max_tokens", 128),
            default_temperature=config.get("temperature"),
            pipeline_kwargs=config.get("pipeline_kwargs"),
        )
    if backend in {"gemini", "google", "google_ai"}:
        return GeminiClient(
            model=config["model"],
            api_key=config.get("api_key"),
            default_temperature=config.get("temperature"),
            default_max_tokens=config.get("max_tokens"),
        )
    if backend in {"openrouter"}:
        return OpenRouterClient(
            model=config["model"],
            api_key=config.get("api_key"),
            default_temperature=config.get("temperature"),
            default_max_tokens=config.get("max_tokens"),
        )
    if backend in {"template", "static"}:
        template = config.get("template")
        if not template:
            raise ValueError("Template backend requires a 'template' field.")
        return TemplateClient(template)

    raise ValueError(f"Unsupported LLM backend '{backend}'.")


class _SafeDefaultDict(dict):
    """dict subclass that returns empty string for missing keys during formatting."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - simple default
        return ""