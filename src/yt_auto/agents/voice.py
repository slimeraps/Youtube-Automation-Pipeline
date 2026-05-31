"""Voice Agent: turns script narration into voice.mp3 via ElevenLabs."""
import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)


class ElevenLabsLike(Protocol):
    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None: ...


class VoiceConfigError(Exception):
    """The voice_category resolved by Script Agent has no voice_id in config."""


class VoiceAgent:
    name = "voice"

    def __init__(
        self,
        elevenlabs: ElevenLabsLike,
        voice_id_for_category: Callable[[str], str],
    ) -> None:
        self._eleven = elevenlabs
        self._lookup_voice = voice_id_for_category

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        narration: str = script["narration"]
        category: str = ctx.metadata.get("voice_category") or script["voice_category"]

        try:
            voice_id = self._lookup_voice(category)
        except KeyError as e:
            raise VoiceConfigError(str(e)) from e

        dest = ctx.run_dir / "voice.mp3"
        await self._eleven.synthesize_to_mp3(text=narration, voice_id=voice_id, dest=dest)
        actual_duration = await probe_duration_s(dest)
        log.info("voice_done", path=str(dest), duration_s=actual_duration)

        return StageResult(
            artifacts={"voice.mp3": dest},
            metadata={
                "voice_id": voice_id,
                "actual_duration_s": actual_duration,
            },
        )
