from pathlib import Path
from typing import Any

import pytest

from yt_auto.clients.elevenlabs import ElevenLabsClient, ElevenLabsError


class _FakeTextToSpeech:
    """Stand-in for `elevenlabs.client.ElevenLabs().text_to_speech`."""

    def __init__(self, audio_bytes: bytes | None = None, raise_with: Exception | None = None) -> None:
        self._audio = audio_bytes
        self._raise = raise_with
        self.calls: list[dict[str, Any]] = []

    def convert(self, *, voice_id: str, text: str, model_id: str, output_format: str) -> Any:
        self.calls.append({
            "voice_id": voice_id, "text": text,
            "model_id": model_id, "output_format": output_format,
        })
        if self._raise:
            raise self._raise
        # SDK returns an iterator of bytes; we mimic that.
        assert self._audio is not None
        return iter([self._audio])


class _FakeElevenSDK:
    def __init__(self, text_to_speech: _FakeTextToSpeech) -> None:
        self.text_to_speech = text_to_speech


@pytest.mark.asyncio
async def test_synthesize_to_mp3_writes_file(tmp_path: Path) -> None:
    fake_tts = _FakeTextToSpeech(audio_bytes=b"\xff\xfb\x90\x00" * 100)
    sdk = _FakeElevenSDK(fake_tts)
    client = ElevenLabsClient(api_key="k", model="eleven_multilingual_v2", _sdk=sdk)

    dest = tmp_path / "voice.mp3"
    await client.synthesize_to_mp3(text="hello world", voice_id="vid-1", dest=dest)

    assert dest.exists()
    assert dest.read_bytes() == b"\xff\xfb\x90\x00" * 100
    assert fake_tts.calls[0]["voice_id"] == "vid-1"
    assert fake_tts.calls[0]["text"] == "hello world"
    assert fake_tts.calls[0]["model_id"] == "eleven_multilingual_v2"
    assert "mp3" in fake_tts.calls[0]["output_format"]


@pytest.mark.asyncio
async def test_synthesize_to_mp3_wraps_sdk_errors(tmp_path: Path) -> None:
    fake_tts = _FakeTextToSpeech(raise_with=RuntimeError("simulated 401"))
    client = ElevenLabsClient(api_key="k", model="m", _sdk=_FakeElevenSDK(fake_tts))

    with pytest.raises(ElevenLabsError, match="simulated 401"):
        await client.synthesize_to_mp3(text="hi", voice_id="v", dest=tmp_path / "voice.mp3")
