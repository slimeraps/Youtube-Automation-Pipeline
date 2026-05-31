from pathlib import Path

import pytest

from yt_auto.agents.caption import CaptionAgent
from yt_auto.clients.whisper import Segment
from yt_auto.pipeline.context import RunContext


class _FakeWhisper:
    def __init__(self, segments: list[Segment]) -> None:
        self._segments = segments
        self.transcribed: list[Path] = []

    async def transcribe(self, audio: Path) -> list[Segment]:
        self.transcribed.append(audio)
        return self._segments


def _ctx(tmp_path: Path) -> RunContext:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")
    return RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"voice.mp3": audio},
        metadata={},
    )


@pytest.mark.asyncio
async def test_caption_agent_writes_well_formed_srt(tmp_path: Path) -> None:
    fake = _FakeWhisper([
        Segment(start_s=0.0, end_s=2.0, text="Hello world."),
        Segment(start_s=2.5, end_s=4.25, text="And goodbye."),
    ])
    agent = CaptionAgent(whisper=fake)

    result = await agent.run(_ctx(tmp_path))

    srt_path = result.artifacts["captions.srt"]
    assert srt_path == tmp_path / "captions.srt"
    text = srt_path.read_text(encoding="utf-8")
    # SRT cue 1
    assert "1\n00:00:00,000 --> 00:00:02,000\nHello world." in text
    # SRT cue 2
    assert "2\n00:00:02,500 --> 00:00:04,250\nAnd goodbye." in text
    # Metadata
    assert result.metadata["word_count"] == 4  # "Hello world. And goodbye." → 4 tokens


@pytest.mark.asyncio
async def test_caption_agent_handles_empty_transcript(tmp_path: Path) -> None:
    agent = CaptionAgent(whisper=_FakeWhisper([]))

    with pytest.raises(ValueError, match="whisper returned zero segments"):
        await agent.run(_ctx(tmp_path))
