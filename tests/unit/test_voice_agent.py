import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.voice import VoiceAgent, VoiceConfigError
from yt_auto.pipeline.context import RunContext


class _FakeEleven:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mp3_bytes = b"\xff\xfb" + b"\x00" * 1000

    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None:
        self.calls.append({"text": text, "voice_id": voice_id, "dest": dest})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.mp3_bytes)


async def _fake_probe(_path: Path) -> float:
    return 47.5  # pretend mp3 duration


def _make_ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="01HVOICE",
        topic="t",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={"voice_category": "calm_narrator"},
    )


def _write_script_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "narration": "Once upon a time there was a curious traveler.",
                "voice_category": "calm_narrator",
            }
        )
    )


@pytest.mark.asyncio
async def test_voice_agent_synthesizes_and_records_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("yt_auto.agents.voice.probe_duration_s", _fake_probe)
    fake = _FakeEleven()
    agent = VoiceAgent(
        elevenlabs=fake,
        voice_id_for_category=lambda cat: "vid-calm" if cat == "calm_narrator" else "fail",
    )
    ctx = _make_ctx(tmp_path)
    _write_script_json(ctx.artifacts["script.json"])

    result = await agent.run(ctx)

    voice_path = result.artifacts["voice.mp3"]
    assert voice_path == tmp_path / "voice.mp3"
    assert voice_path.exists()
    assert fake.calls[0]["voice_id"] == "vid-calm"
    assert fake.calls[0]["text"] == "Once upon a time there was a curious traveler."
    assert result.metadata["voice_id"] == "vid-calm"
    assert result.metadata["actual_duration_s"] == 47.5


@pytest.mark.asyncio
async def test_voice_agent_uses_category_from_script_when_missing_in_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("yt_auto.agents.voice.probe_duration_s", _fake_probe)
    fake = _FakeEleven()
    agent = VoiceAgent(
        elevenlabs=fake,
        voice_id_for_category=lambda cat: "vid-deep" if cat == "deep_documentary" else "x",
    )
    ctx = RunContext(
        run_id="r",
        topic="t",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={},  # no voice_category in metadata; must fall back to script.json
    )
    ctx.artifacts["script.json"].parent.mkdir(parents=True, exist_ok=True)
    ctx.artifacts["script.json"].write_text(
        json.dumps(
            {
                "narration": "Words.",
                "voice_category": "deep_documentary",
            }
        )
    )

    result = await agent.run(ctx)

    assert result.metadata["voice_id"] == "vid-deep"


@pytest.mark.asyncio
async def test_voice_agent_raises_for_unconfigured_voice(tmp_path: Path) -> None:
    def lookup(_cat: str) -> str:
        raise KeyError("no voice_id configured for category: calm_narrator")

    agent = VoiceAgent(elevenlabs=_FakeEleven(), voice_id_for_category=lookup)
    ctx = _make_ctx(tmp_path)
    _write_script_json(ctx.artifacts["script.json"])

    with pytest.raises(VoiceConfigError, match="no voice_id"):
        await agent.run(ctx)
