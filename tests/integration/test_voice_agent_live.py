"""Live test against ElevenLabs. Run with: pytest -m integration."""
import json
import os
from pathlib import Path

import pytest

from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.config import get_settings
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("ELEVENLABS_API_KEY"),
    reason="ELEVENLABS_API_KEY not set",
)
async def test_voice_agent_against_real_elevenlabs(tmp_path: Path) -> None:
    settings = get_settings()
    # Sanity: at least one voice id must be configured.
    try:
        voice_id = settings.elevenlabs_voice_for_category("calm_narrator")
    except KeyError:
        pytest.skip("ELEVENLABS_VOICE_CALM_NARRATOR not set in .env")

    client = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    agent = VoiceAgent(elevenlabs=client, voice_id_for_category=settings.elevenlabs_voice_for_category)

    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps({
        "narration": "This is a brief test of the voice agent. One short sentence.",
        "voice_category": "calm_narrator",
    }))
    ctx = RunContext(
        run_id="voice-smoke", topic="t", format="short", visibility="private",
        run_dir=tmp_path,
        artifacts={"script.json": script_path},
        metadata={"voice_category": "calm_narrator"},
    )

    result = await agent.run(ctx)

    assert result.artifacts["voice.mp3"].stat().st_size > 1000  # at least 1 KB of audio
    assert result.metadata["actual_duration_s"] > 0
    assert result.metadata["voice_id"] == voice_id
