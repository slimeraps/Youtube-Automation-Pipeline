import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.render import RenderAgent
from yt_auto.pipeline.context import RunContext


async def _fake_probe(path: Path) -> float:
    return 47.5 if path.name == "final.mp4" else 0.0


def _make_ctx(tmp_path: Path) -> RunContext:
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"format": "long"}))
    video = tmp_path / "video_silent.mp4"
    audio = tmp_path / "voice.mp3"
    srt = tmp_path / "captions.srt"
    for p in (video, audio, srt):
        p.write_bytes(b"fake")
    return RunContext(
        run_id="r",
        topic="t",
        format="long",
        visibility="public",
        run_dir=tmp_path,
        artifacts={
            "script.json": script,
            "video_silent.mp4": video,
            "voice.mp3": audio,
            "captions.srt": srt,
        },
        metadata={},
    )


@pytest.mark.asyncio
async def test_render_agent_invokes_render_final_with_correct_dims_for_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_render_final(**kwargs: Any) -> None:
        captured.update(kwargs)
        kwargs["dest"].write_bytes(b"final_mp4")

    monkeypatch.setattr("yt_auto.agents.render.render_final", fake_render_final)
    monkeypatch.setattr("yt_auto.agents.render.probe_duration_s", _fake_probe)

    agent = RenderAgent()
    result = await agent.run(_make_ctx(tmp_path))

    assert captured["width"] == 1920
    assert captured["height"] == 1080
    assert captured["dest"] == tmp_path / "final.mp4"
    assert result.artifacts["final.mp4"].exists()
    assert result.metadata["final_duration_s"] == 47.5
    assert result.metadata["file_size_mb"] == pytest.approx(
        len(b"final_mp4") / (1024 * 1024), rel=1e-3
    )


@pytest.mark.asyncio
async def test_render_agent_uses_short_dims_when_format_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_render_final(**kwargs: Any) -> None:
        captured.update(kwargs)
        kwargs["dest"].write_bytes(b"final_mp4_short")

    monkeypatch.setattr("yt_auto.agents.render.render_final", fake_render_final)
    monkeypatch.setattr("yt_auto.agents.render.probe_duration_s", _fake_probe)

    ctx = _make_ctx(tmp_path)
    # Override script.json to short
    ctx.artifacts["script.json"].write_text(json.dumps({"format": "short"}))
    ctx = RunContext(
        run_id=ctx.run_id,
        topic=ctx.topic,
        format="short",
        visibility=ctx.visibility,
        run_dir=ctx.run_dir,
        artifacts=ctx.artifacts,
        metadata=ctx.metadata,
    )

    agent = RenderAgent()
    await agent.run(ctx)

    assert captured["width"] == 1080
    assert captured["height"] == 1920
