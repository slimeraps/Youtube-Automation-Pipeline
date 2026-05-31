import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.pexels import Clip, PexelsClient

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _stub_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_videos_returns_clips_with_best_video_file() -> None:
    body = (FIXTURES / "pexels_search_response.json").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.pexels.com"
        assert "videos/search" in request.url.path
        assert request.url.params["query"] == "red sunset"
        assert request.url.params["per_page"] == "10"
        assert request.headers["Authorization"] == "test-key"
        return httpx.Response(200, content=body)

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="test-key", _http=http)
        clips = await client.search_videos(query="red sunset", per_page=10)

    assert len(clips) == 3
    assert clips[0] == Clip(id=100, duration_s=12, width=1920, height=1080,
                            url="https://example.com/hd.mp4")
    assert clips[1].url == "https://example.com/hd2.mp4"
    assert clips[2].url == "https://example.com/hd3.mp4"


@pytest.mark.asyncio
async def test_download_writes_file_to_dest(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(200, content=b"FAKE_MP4_BYTES")

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="k", _http=http)
        dest = tmp_path / "clip.mp4"
        await client.download(url="https://example.com/hd.mp4", dest=dest)

    assert dest.read_bytes() == b"FAKE_MP4_BYTES"


@pytest.mark.asyncio
async def test_search_videos_returns_empty_list_when_no_videos() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({
            "page": 1, "per_page": 10, "total_results": 0, "videos": [],
        }))

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="k", _http=http)
        clips = await client.search_videos(query="zzzzz", per_page=10)
    assert clips == []
