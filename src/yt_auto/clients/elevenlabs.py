"""Async wrapper around the (sync) elevenlabs SDK for MP3 text-to-speech."""

import asyncio
from pathlib import Path
from typing import Any

from yt_auto.logging import get_logger

log = get_logger(__name__)


class ElevenLabsError(Exception):
    """Wraps any failure from the ElevenLabs SDK."""


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        model: str = "eleven_multilingual_v2",
        *,
        output_format: str = "mp3_44100_128",
        _sdk: Any = None,
    ) -> None:
        self._model = model
        self._output_format = output_format
        if _sdk is not None:
            self._sdk = _sdk
        else:
            from elevenlabs.client import ElevenLabs  # imported lazily for testability

            self._sdk = ElevenLabs(api_key=api_key)

    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None:
        """Synthesize `text` with `voice_id` and write the resulting MP3 to `dest`."""

        def _call() -> bytes:
            try:
                chunks = self._sdk.text_to_speech.convert(
                    voice_id=voice_id,
                    text=text,
                    model_id=self._model,
                    output_format=self._output_format,
                )
                return b"".join(chunks)
            except Exception as e:
                raise ElevenLabsError(str(e)) from e

        audio = await asyncio.to_thread(_call)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(audio)
        log.info("elevenlabs_synthesized", bytes=len(audio), dest=str(dest), voice_id=voice_id)
