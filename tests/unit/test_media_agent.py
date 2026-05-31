import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.media import MediaAgent, MediaError, pick_best_clip, rescale_scenes
from yt_auto.clients.pexels import Clip
from yt_auto.pipeline.context import RunContext


def test_rescale_scenes_preserves_relative_proportions() -> None:
    scenes = [
        {"index": 0, "start_s": 0.0, "end_s": 10.0, "narration_excerpt": "a"},
        {"index": 1, "start_s": 10.0, "end_s": 30.0, "narration_excerpt": "b"},
        {"index": 2, "start_s": 30.0, "end_s": 50.0, "narration_excerpt": "c"},
    ]
    rescaled = rescale_scenes(scenes, target_total_duration_s=25.0)
    # Original durations 10/20/20 in a 50s total → 0.2/0.4/0.4 share → 5/10/10s
    assert rescaled[0]["end_s"] == pytest.approx(5.0)
    assert rescaled[1]["start_s"] == pytest.approx(5.0)
    assert rescaled[1]["end_s"] == pytest.approx(15.0)
    assert rescaled[2]["end_s"] == pytest.approx(25.0)


def test_pick_best_clip_prefers_shortest_at_or_above_target() -> None:
    clips = [
        Clip(id=1, duration_s=5, width=1920, height=1080, url="a"),
        Clip(id=2, duration_s=12, width=1920, height=1080, url="b"),
        Clip(id=3, duration_s=8, width=1920, height=1080, url="c"),
        Clip(id=4, duration_s=20, width=1920, height=1080, url="d"),
    ]
    picked = pick_best_clip(clips, target_duration_s=7.0)
    assert picked.id == 3  # shortest that is >= 7s


def test_pick_best_clip_falls_back_to_longest_when_all_shorter() -> None:
    clips = [
        Clip(id=1, duration_s=2, width=1920, height=1080, url="a"),
        Clip(id=2, duration_s=4, width=1920, height=1080, url="b"),
        Clip(id=3, duration_s=3, width=1920, height=1080, url="c"),
    ]
    picked = pick_best_clip(clips, target_duration_s=10.0)
    assert picked.id == 2  # longest available; agent will loop it


def test_pick_best_clip_empty_list_raises() -> None:
    with pytest.raises(MediaError, match="no clips"):
        pick_best_clip([], target_duration_s=5.0)


class _FakePexels:
    def __init__(self, results_by_query: dict[str, list[Clip]]) -> None:
        self._results = results_by_query
        self.searches: list[tuple[str, int]] = []
        self.downloads: list[tuple[str, Path]] = []

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        self.searches.append((query, per_page))
        return self._results.get(query, [])

    async def download(self, *, url: str, dest: Path) -> None:
        self.downloads.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE")


def _make_async_no_op(record: list[Any]) -> Callable[..., Awaitable[None]]:
    async def _fn(**kwargs: Any) -> None:
        record.append(kwargs)
    return _fn


def _make_ctx(tmp_path: Path) -> RunContext:
    script = tmp_path / "script.json"
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"fake")
    script.write_text(json.dumps({
        "format": "short",
        "scenes": [
            {"index": 0, "start_s": 0.0, "end_s": 5.0, "narration_excerpt": "a",
             "visual_prompt": "x", "pexels_query": "sunset beach"},
            {"index": 1, "start_s": 5.0, "end_s": 10.0, "narration_excerpt": "b",
             "visual_prompt": "y", "pexels_query": "mountain trail"},
        ],
    }))
    return RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": script, "voice.mp3": voice},
        metadata={"actual_duration_s": 8.0},
    )


@pytest.mark.asyncio
async def test_media_agent_searches_downloads_prepares_concats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pexels = _FakePexels({
        "sunset beach": [Clip(id=1, duration_s=10, width=1920, height=1080, url="u1")],
        "mountain trail": [Clip(id=2, duration_s=10, width=1920, height=1080, url="u2")],
    })
    prepare_calls: list[Any] = []
    concat_calls: list[Any] = []
    monkeypatch.setattr("yt_auto.agents.media.prepare_clip", _make_async_no_op(prepare_calls))

    async def fake_concat(**kwargs: Any) -> None:
        concat_calls.append(kwargs)
        kwargs["dest"].write_bytes(b"silent_video")
    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(pexels=fake_pexels, per_page=10)
    result = await agent.run(_make_ctx(tmp_path))

    # Both queries were searched
    assert {s[0] for s in fake_pexels.searches} == {"sunset beach", "mountain trail"}
    # Both clips were downloaded
    assert len(fake_pexels.downloads) == 2
    # prepare_clip called twice (one per scene) with rescaled target durations.
    # actual_duration_s=8 vs script total=10 → scale 0.8: 5→4s, 5→4s
    assert len(prepare_calls) == 2
    assert prepare_calls[0]["target_duration_s"] == pytest.approx(4.0)
    assert prepare_calls[1]["target_duration_s"] == pytest.approx(4.0)
    # concat called with two prepared clips
    assert len(concat_calls) == 1
    assert len(concat_calls[0]["clips"]) == 2
    assert result.artifacts["video_silent.mp4"] == tmp_path / "video_silent.mp4"
    assert result.metadata["clip_count"] == 2


@pytest.mark.asyncio
async def test_media_agent_fails_when_scene_has_no_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pexels = _FakePexels({"sunset beach": []})  # zero results
    monkeypatch.setattr("yt_auto.agents.media.prepare_clip", _make_async_no_op([]))
    monkeypatch.setattr("yt_auto.agents.media.concat_clips", _make_async_no_op([]))

    agent = MediaAgent(pexels=fake_pexels, per_page=10)
    with pytest.raises(MediaError, match="no clips"):
        await agent.run(_make_ctx(tmp_path))
