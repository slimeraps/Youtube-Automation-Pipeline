"""Live test against Pexels. Run with: pytest -m integration."""
import os
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.pexels import PexelsClient

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("PEXELS_API_KEY"),
    reason="PEXELS_API_KEY not set",
)
async def test_pexels_search_returns_clips(tmp_path: Path) -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = PexelsClient(api_key=os.environ["PEXELS_API_KEY"], _http=http)
        clips = await client.search_videos(query="sunset beach", per_page=5)
        assert len(clips) > 0
        assert all(c.duration_s > 0 for c in clips)

        # Download the first one to verify download flow
        dest = tmp_path / "clip.mp4"
        await client.download(url=clips[0].url, dest=dest)
        assert dest.stat().st_size > 10_000  # at least 10 KB
