"""Tests for ComfyUIClient. All HTTP is faked via httpx MockTransport."""

import json
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.comfyui import ComfyUIClient, ComfyUIError

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _history_payload(prompt_id: str) -> dict:
    raw = json.loads((FIXTURE_DIR / "comfyui_history_done.json").read_text())
    return {prompt_id: raw["PROMPT_ID_HERE"]}


def test_workflow_template_substitutes_prompt_dims_seed() -> None:
    client = ComfyUIClient(base_url="http://x")
    wf = client._build_workflow(prompt="a cat", width=1024, height=768, seed=42)
    assert wf["5"]["inputs"]["width"] == 1024
    assert wf["5"]["inputs"]["height"] == 768
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["6"]["inputs"]["text"] == "a cat"


@pytest.mark.asyncio
async def test_generate_image_happy_path(tmp_path: Path) -> None:
    prompt_id = "abc-123"
    calls: list[tuple[str, str]] = []
    png_bytes = b"\x89PNG\r\n\x1a\nFAKEPNG"

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if req.method == "GET" and req.url.path == f"/history/{prompt_id}":
            return httpx.Response(200, json=_history_payload(prompt_id))
        if req.method == "GET" and req.url.path == "/view":
            return httpx.Response(200, content=png_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)

    dest = tmp_path / "out.png"
    await client.generate_image(
        prompt="majestic mountain", width=1024, height=1024, seed=7, dest=dest
    )

    assert dest.read_bytes() == png_bytes
    assert ("POST", "/prompt") in calls
    assert ("GET", f"/history/{prompt_id}") in calls
    assert ("GET", "/view") in calls


@pytest.mark.asyncio
async def test_generate_image_polls_until_done(tmp_path: Path) -> None:
    prompt_id = "abc-123"
    history_calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal history_calls
        if req.method == "POST" and req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if req.method == "GET" and req.url.path == f"/history/{prompt_id}":
            history_calls += 1
            if history_calls < 3:
                return httpx.Response(200, json={})  # not done yet
            return httpx.Response(200, json=_history_payload(prompt_id))
        if req.method == "GET" and req.url.path == "/view":
            return httpx.Response(200, content=b"PNG")
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)
    dest = tmp_path / "out.png"
    await client.generate_image(prompt="x", width=64, height=64, seed=1, dest=dest)
    assert history_calls == 3


@pytest.mark.asyncio
async def test_generate_image_raises_on_submit_failure(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)
    with pytest.raises(ComfyUIError, match="submit"):
        await client.generate_image(
            prompt="x", width=64, height=64, seed=1, dest=tmp_path / "out.png"
        )


@pytest.mark.asyncio
async def test_generate_image_raises_on_poll_timeout(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={"prompt_id": "abc"})
        return httpx.Response(200, json={})  # always pending

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(
        base_url="http://comfy", _http=http, poll_interval_s=0.0, timeout_s=0.05
    )
    with pytest.raises(ComfyUIError, match="timeout"):
        await client.generate_image(
            prompt="x", width=64, height=64, seed=1, dest=tmp_path / "out.png"
        )


@pytest.mark.asyncio
async def test_ping_returns_true_when_reachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http)
    assert await client.ping() is True


@pytest.mark.asyncio
async def test_ping_returns_false_when_unreachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http)
    assert await client.ping() is False
