from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from yt_auto.clients.whisper import Segment, WhisperClient


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str


class _FakeWhisperModel:
    """Stand-in for faster_whisper.WhisperModel."""

    def __init__(self, segments: list[_FakeSegment]) -> None:
        self._segments = segments

    def transcribe(
        self, _audio: str, **_kwargs: Any
    ) -> tuple[Iterator[_FakeSegment], dict[str, Any]]:
        return iter(self._segments), {"language": "en", "duration": 4.0}


@pytest.mark.asyncio
async def test_transcribe_returns_segments(tmp_path: Path) -> None:
    fake_model = _FakeWhisperModel([
        _FakeSegment(start=0.0, end=2.0, text="Hello world."),
        _FakeSegment(start=2.0, end=4.0, text="Goodbye."),
    ])
    client = WhisperClient(model_name="small", _model=fake_model)

    segments = await client.transcribe(tmp_path / "audio.mp3")

    assert len(segments) == 2
    assert segments[0] == Segment(start_s=0.0, end_s=2.0, text="Hello world.")
    assert segments[1] == Segment(start_s=2.0, end_s=4.0, text="Goodbye.")
