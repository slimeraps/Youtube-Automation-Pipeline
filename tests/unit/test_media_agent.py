"""Tests for the strategy-based MediaAgent."""

import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.media import MediaAgent, MediaError, rescale_scenes
from yt_auto.agents.sources import SceneSource, SceneSourceError
from yt_auto.pipeline.context import RunContext


def test_rescale_scenes_preserves_relative_proportions() -> None:
    scenes = [
        {"index": 0, "start_s": 0.0, "end_s": 10.0, "narration_excerpt": "a"},
        {"index": 1, "start_s": 10.0, "end_s": 30.0, "narration_excerpt": "b"},
        {"index": 2, "start_s": 30.0, "end_s": 50.0, "narration_excerpt": "c"},
    ]
    rescaled = rescale_scenes(scenes, target_total_duration_s=25.0)
    assert rescaled[0]["end_s"] == pytest.approx(5.0)
    assert rescaled[1]["end_s"] == pytest.approx(15.0)
    assert rescaled[2]["end_s"] == pytest.approx(25.0)


class _RecordingSource:
    def __init__(self, *, fail_on_indexes: set[int] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_on = fail_on_indexes or set()

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        self.calls.append({"index": scene["index"], "dest": dest})
        if scene["index"] in self._fail_on:
            raise SceneSourceError(f"forced failure for scene {scene['index']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"CLIP")


def _make_ctx(tmp_path: Path, *, video_style: str = "x") -> RunContext:
    script = tmp_path / "script.json"
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"fake")
    script.write_text(
        json.dumps(
            {
                "format": "short",
                "video_style": video_style,
                "scenes": [
                    {
                        "index": 0,
                        "start_s": 0.0,
                        "end_s": 5.0,
                        "narration_excerpt": "a",
                        "visual_prompt": "x",
                        "image_prompt": "a sunset over a beach",
                        "pexels_query": "sunset beach",
                    },
                    {
                        "index": 1,
                        "start_s": 5.0,
                        "end_s": 10.0,
                        "narration_excerpt": "b",
                        "visual_prompt": "y",
                        "image_prompt": "a mountain trail at dawn",
                        "pexels_query": "mountain trail",
                    },
                ],
            }
        )
    )
    return RunContext(
        run_id="r",
        topic="t",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": script, "voice.mp3": voice},
        metadata={"actual_duration_s": 8.0},
    )


@pytest.mark.asyncio
async def test_media_agent_uses_primary_when_all_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=fallback)
    result = await agent.run(_make_ctx(tmp_path))

    assert [c["index"] for c in primary.calls] == [0, 1]
    assert fallback.calls == []
    assert result.metadata["clip_count"] == 2
    assert result.metadata["source_counts"] == {"primary": 2, "fallback": 0}


@pytest.mark.asyncio
async def test_media_agent_falls_back_per_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource(fail_on_indexes={1})
    fallback = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=fallback)
    result = await agent.run(_make_ctx(tmp_path))

    assert [c["index"] for c in primary.calls] == [0, 1]
    assert [c["index"] for c in fallback.calls] == [1]
    assert result.metadata["source_counts"] == {"primary": 1, "fallback": 1}


@pytest.mark.asyncio
async def test_media_agent_raises_when_both_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource(fail_on_indexes={0})
    fallback = _RecordingSource(fail_on_indexes={0})
    monkeypatch.setattr(
        "yt_auto.agents.media.concat_clips",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not concat")),
    )
    agent = MediaAgent(primary=primary, fallback=fallback)
    with pytest.raises(MediaError, match="both sources"):
        await agent.run(_make_ctx(tmp_path))


@pytest.mark.asyncio
async def test_media_agent_works_with_only_one_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=None)
    result = await agent.run(_make_ctx(tmp_path))
    assert result.metadata["source_counts"]["primary"] == 2


@pytest.mark.asyncio
async def test_media_agent_calls_primary_factory_with_video_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received_styles: list[str] = []

    def factory(video_style: str) -> _RecordingSource:
        received_styles.append(video_style)
        return _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=factory, fallback=None)
    await agent.run(_make_ctx(tmp_path, video_style="oil painting, romanticist"))
    assert received_styles == ["oil painting, romanticist"]


@pytest.mark.asyncio
async def test_media_agent_skips_primary_when_healthcheck_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def failing_healthcheck() -> bool:
        return False

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(
        primary=primary, fallback=fallback, primary_healthcheck=failing_healthcheck
    )
    result = await agent.run(_make_ctx(tmp_path))

    assert primary.calls == []  # never invoked
    assert [c["index"] for c in fallback.calls] == [0, 1]
    assert result.metadata["source_counts"] == {"primary": 0, "fallback": 2}
    assert result.metadata["primary_healthy"] is False


@pytest.mark.asyncio
async def test_media_agent_uses_primary_when_healthcheck_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def ok_healthcheck() -> bool:
        return True

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(
        primary=primary, fallback=fallback, primary_healthcheck=ok_healthcheck
    )
    result = await agent.run(_make_ctx(tmp_path))
    assert [c["index"] for c in primary.calls] == [0, 1]
    assert result.metadata["primary_healthy"] is True
