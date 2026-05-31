"""Thin async wrapper around google-genai for JSON-mode calls."""
import asyncio
import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from yt_auto.logging import get_logger

log = get_logger(__name__)


class GeminiError(Exception):
    """Base for all Gemini client errors."""


class GeminiTransportError(GeminiError):
    """Network / 429 / 5xx after retries exhausted."""


class GeminiInvalidJSONError(GeminiError):
    """The model returned content that isn't valid JSON."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class GeminiClient:
    """Async JSON-mode Gemini client with transport-level retries."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_transport_retries: int = 3,
        max_json_retries: int = 2,
        initial_backoff_s: float = 1.0,
        _genai_client: Any = None,
    ) -> None:
        self._model = model
        self._max_transport_retries = max_transport_retries
        self._max_json_retries = max_json_retries
        self._initial_backoff = initial_backoff_s
        self._client = _genai_client or genai.Client(api_key=api_key)

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        """Send `prompt`, expect JSON, return parsed dict.

        Retries malformed JSON up to `max_json_retries` times with the same prompt
        (gemini occasionally drops braces despite JSON mode).
        """
        config = genai_types.GenerateContentConfig(response_mime_type="application/json")
        last_raw = ""
        last_exc: json.JSONDecodeError | None = None
        for attempt in range(1, self._max_json_retries + 2):  # initial + retries
            text = await self._call_with_retries(prompt=prompt, config=config)
            try:
                return json.loads(text)  # type: ignore[no-any-return]
            except json.JSONDecodeError as e:
                last_raw = text
                last_exc = e
                log.warning(
                    "gemini_invalid_json",
                    attempt=attempt,
                    max_attempts=self._max_json_retries + 1,
                    snippet=text[:120],
                )
        raise GeminiInvalidJSONError(
            f"model returned non-JSON after {self._max_json_retries} retries: {last_exc}",
            raw_text=last_raw,
        )

    async def _call_with_retries(self, *, prompt: str, config: Any) -> str:
        backoff = self._initial_backoff
        last_exc: Exception | None = None
        for attempt in range(1, self._max_transport_retries + 1):
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
                text: str = resp.text  # type: ignore[assignment]
                return text
            except Exception as e:
                last_exc = e
                log.warning(
                    "gemini_transport_error",
                    attempt=attempt,
                    max_attempts=self._max_transport_retries,
                    error=str(e),
                )
                if attempt >= self._max_transport_retries:
                    break
                if backoff > 0:
                    await asyncio.sleep(backoff)
                backoff *= 4
        raise GeminiTransportError(
            f"gemini call failed after {self._max_transport_retries} attempts: {last_exc}"
        ) from last_exc
