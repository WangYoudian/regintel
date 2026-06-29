"""LLM API client — wraps internal LLM API with retry + structured output."""

from __future__ import annotations

import json
import logging
from typing import Optional, TypeVar

import httpx
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Lightweight client for internal LLM API with JSON mode support."""

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        model: str = "",
        timeout: int = 60,
    ):
        self.endpoint = endpoint or settings.llm_api_endpoint
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout

    def chat(self, messages: list[dict], temperature: float = 0.1) -> str:
        """Send a chat completion request and return text response."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            resp = httpx.post(
                f"{self.endpoint}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            return ""

    def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        max_retries: int = 2,
    ) -> Optional[T]:
        """Request structured JSON output parsed into a Pydantic model."""
        system_note = (
            f"Respond in JSON matching this schema: "
            f"{json.dumps(response_model.model_json_schema(), indent=2)}"
        )
        msgs = [{"role": "system", "content": system_note}, *messages]

        for attempt in range(max_retries + 1):
            try:
                payload = {
                    "model": self.model,
                    "messages": msgs,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                }
                resp = httpx.post(
                    f"{self.endpoint}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(raw)
                return response_model.model_validate(data)
            except Exception as e:
                logger.warning(
                    f"Structured call attempt {attempt + 1} failed: {e}"
                )
                if attempt == max_retries:
                    return None
        return None

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        try:
            payload = {
                "model": settings.embedding_model,
                "input": text,
            }
            resp = httpx.post(
                f"{self.endpoint}/embeddings",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception:
            logger.warning(
                "LLM embedding endpoint unavailable; "
                "fall through to local embedding service."
            )
            return []

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
