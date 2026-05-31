import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from yt_auto.clients.gemini import (
    GeminiClient,
    GeminiInvalidJSONError,
    GeminiTransportError,
)


@dataclass
class _FakeResponse:
    text: str


class _FakeAsyncModels:
    """Minimal stand-in for `genai.Client().aio.models`."""

    def __init__(self, handler: Callable[[str], Awaitable[_FakeResponse]]) -> None:
        self._handler = handler
        self.calls: list[dict[str, object]] = []

    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return await self._handler(contents)


class _FakeAio:
    def __init__(self, models: _FakeAsyncModels) -> None:
        self.models = models


class _FakeGenaiClient:
    def __init__(self, models: _FakeAsyncModels) -> None:
        self.aio = _FakeAio(models)


def _ok_with(text: str) -> Callable[[str], Awaitable[_FakeResponse]]:
    async def _handler(_prompt: str) -> _FakeResponse:
        return _FakeResponse(text=text)

    return _handler


@pytest.mark.asyncio
async def test_generate_json_parses_valid_response() -> None:
    handler = _ok_with(json.dumps({"hello": "world"}))
    models = _FakeAsyncModels(handler)
    client = GeminiClient(api_key="k", model="m", _genai_client=_FakeGenaiClient(models))

    result = await client.generate_json("prompt")

    assert result == {"hello": "world"}
    assert models.calls[0]["model"] == "m"
    assert models.calls[0]["contents"] == "prompt"


@pytest.mark.asyncio
async def test_generate_json_retries_on_invalid_json_then_succeeds() -> None:
    attempts = {"n": 0}

    async def handler(_prompt: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return _FakeResponse(text="not json {{{")
        return _FakeResponse(text=json.dumps({"ok": True}))

    client = GeminiClient(
        api_key="k",
        model="m",
        max_json_retries=2,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    result = await client.generate_json("prompt")
    assert result == {"ok": True}
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_generate_json_gives_up_after_max_json_retries() -> None:
    async def handler(_prompt: str) -> _FakeResponse:
        return _FakeResponse(text="still not json")

    client = GeminiClient(
        api_key="k",
        model="m",
        max_json_retries=2,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    with pytest.raises(GeminiInvalidJSONError):
        await client.generate_json("prompt")


@pytest.mark.asyncio
async def test_generate_json_retries_on_transport_error_then_succeeds() -> None:
    attempts = {"n": 0}

    async def handler(_prompt: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("simulated 429")
        return _FakeResponse(text=json.dumps({"ok": True}))

    client = GeminiClient(
        api_key="k",
        model="m",
        max_transport_retries=3,
        initial_backoff_s=0,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    result = await client.generate_json("prompt")
    assert result == {"ok": True}
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_generate_json_gives_up_after_max_retries() -> None:
    async def handler(_prompt: str) -> _FakeResponse:
        raise RuntimeError("always fails")

    client = GeminiClient(
        api_key="k",
        model="m",
        max_transport_retries=2,
        initial_backoff_s=0,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    with pytest.raises(GeminiTransportError):
        await client.generate_json("prompt")
