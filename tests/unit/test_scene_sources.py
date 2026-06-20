"""Tests for SceneSource protocol implementations."""

from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.sources import PexelsSource, SceneSourceError
from yt_auto.clients.pexels import Clip


class _FakePexels:
    def __init__(self, results: list[Clip]) -> None:
        self._results = results
        self.searches: list[str] = []
        self.downloads: list[tuple[str, Path]] = []

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        self.searches.append(query)
        return self._results

    async def download(self, *, url: str, dest: Path) -> None:
        self.downloads.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE")


def _scene(**overrides: Any) -> dict[str, Any]:
    base = {
        "index": 0,
        "start_s": 0.0,
        "end_s": 4.0,
        "narration_excerpt": "x",
        "visual_prompt": "x",
        "image_prompt": "a mountain at sunset, dramatic light",
        "pexels_query": "mountain sunset",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_pexels_source_searches_downloads_prepares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakePexels(
        [Clip(id=1, duration_s=10, width=1920, height=1080, url="http://x/a.mp4")]
    )
    prepare_calls: list[dict[str, Any]] = []

    async def fake_prepare(**kwargs: Any) -> None:
        prepare_calls.append(kwargs)
        kwargs["dest"].write_bytes(b"PREPARED")

    monkeypatch.setattr("yt_auto.agents.sources.prepare_clip", fake_prepare)

    source = PexelsSource(pexels=fake, per_page=10)
    dest = tmp_path / "scene_000.mp4"
    await source.produce_clip(
        scene=_scene(),
        target_duration_s=4.0,
        width=1920,
        height=1080,
        fps=30,
        dest=dest,
    )

    assert fake.searches == ["mountain sunset"]
    assert len(fake.downloads) == 1
    assert prepare_calls[0]["target_duration_s"] == 4.0
    assert prepare_calls[0]["dest"] == dest


@pytest.mark.asyncio
async def test_pexels_source_raises_on_no_clips(tmp_path: Path) -> None:
    fake = _FakePexels([])
    source = PexelsSource(pexels=fake, per_page=10)
    with pytest.raises(SceneSourceError, match="no clips"):
        await source.produce_clip(
            scene=_scene(),
            target_duration_s=4.0,
            width=1920,
            height=1080,
            fps=30,
            dest=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_pexels_source_wraps_unexpected_exception(tmp_path: Path) -> None:
    class _ExplodingPexels:
        async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
            raise RuntimeError("network down")

        async def download(self, *, url: str, dest: Path) -> None:
            raise AssertionError("should not download")

    source = PexelsSource(pexels=_ExplodingPexels(), per_page=10)
    with pytest.raises(SceneSourceError, match="pexels source failed") as exc_info:
        await source.produce_clip(
            scene=_scene(),
            target_duration_s=4.0,
            width=1920,
            height=1080,
            fps=30,
            dest=tmp_path / "out.mp4",
        )
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "network down" in str(exc_info.value.__cause__)
