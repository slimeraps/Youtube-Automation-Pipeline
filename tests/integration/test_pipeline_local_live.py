"""Full end-to-end against ALL real APIs (Gemini + ElevenLabs + Pexels) + ffmpeg + Whisper.

Heavy: takes 60-180 seconds and costs ~$0.10. Run with: pytest -m integration."""
import os
from pathlib import Path

import pytest

from yt_auto.agents.caption import CaptionAgent
from yt_auto.agents.media import MediaAgent
from yt_auto.agents.render import RenderAgent
from yt_auto.agents.script import ScriptAgent
from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.clients.gemini import GeminiClient
from yt_auto.clients.pexels import PexelsClient
from yt_auto.clients.whisper import WhisperClient
from yt_auto.config import get_settings
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


def _all_keys_present() -> bool:
    return bool(
        os.getenv("GEMINI_API_KEY")
        and os.getenv("ELEVENLABS_API_KEY")
        and os.getenv("PEXELS_API_KEY")
    )


@pytest.mark.skipif(not _all_keys_present(),
                    reason="Gemini / ElevenLabs / Pexels keys required")
async def test_pipeline_local_end_to_end(tmp_path: Path) -> None:
    settings = get_settings()

    ctx = RunContext(
        run_id="pipeline-smoke", topic="the history of espresso",
        format="short", visibility="private",
        run_dir=tmp_path, artifacts={}, metadata={"seed": 11},
    )

    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    ctx = ctx.merge(await ScriptAgent(gemini=gemini).run(ctx))

    eleven = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    voice_agent = VoiceAgent(elevenlabs=eleven,
                             voice_id_for_category=settings.elevenlabs_voice_for_category)
    ctx = ctx.merge(await voice_agent.run(ctx))

    pexels = PexelsClient(api_key=settings.pexels_api_key)
    ctx = ctx.merge(await MediaAgent(pexels=pexels, per_page=settings.pexels_per_page).run(ctx))

    whisper = WhisperClient(model_name=settings.whisper_model,
                            device=settings.whisper_device,
                            compute_type=settings.whisper_compute_type)
    ctx = ctx.merge(await CaptionAgent(whisper=whisper).run(ctx))

    ctx = ctx.merge(await RenderAgent().run(ctx))

    final = ctx.artifacts["final.mp4"]
    assert final.exists()
    assert final.stat().st_size > 1_000_000  # at least 1 MB
    assert ctx.metadata["final_duration_s"] > 10  # short format ≈ 50s
