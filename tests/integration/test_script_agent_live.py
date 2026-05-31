"""Live test against the real Gemini API. Run with: pytest -m integration

Skipped when GEMINI_API_KEY is not set so CI can stay clean.
"""
import json
import os
from pathlib import Path

import pytest

from yt_auto.agents.script import ScriptAgent
from yt_auto.clients.gemini import GeminiClient
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
async def test_script_agent_against_real_gemini(tmp_path: Path) -> None:
    gemini = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    agent = ScriptAgent(gemini=gemini)

    ctx = RunContext(
        run_id="integration-smoke",
        topic="the history of espresso",
        format="short",
        visibility="private",
        run_dir=tmp_path,
        artifacts={},
        metadata={"seed": 7},
    )

    result = await agent.run(ctx)

    data = json.loads(result.artifacts["script.json"].read_text())
    assert len(data["scenes"]) > 0
    assert len(data["narration"].split()) > 50  # short target is 120 ±10%
    assert data["youtube"]["title"]
    assert data["youtube"]["tags"]
    # Visual prompts merged in
    for sc in data["scenes"]:
        assert sc["visual_prompt"]
        assert sc["pexels_query"]
