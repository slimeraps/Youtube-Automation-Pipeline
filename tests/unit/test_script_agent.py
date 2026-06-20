import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.script import ScriptAgent
from yt_auto.pipeline.context import RunContext


class FakeGemini:
    """Returns queued responses; raises if out of responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError(f"Unexpected extra Gemini call:\n{prompt[:200]}")
        return self._responses.pop(0)


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="01HZZ",
        topic="the history of espresso",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={},
        metadata={"seed": 42},
    )


@pytest.mark.asyncio
async def test_script_agent_writes_well_formed_script_json(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)  # tolerant for tiny fixture
    ctx = _ctx(tmp_path)

    result = await agent.run(ctx)

    script_path = result.artifacts["script.json"]
    assert script_path.exists()
    data = json.loads(script_path.read_text())

    assert data["topic"] == "the history of espresso"
    assert data["format"] == "short"
    assert data["voice_category"] in {
        "calm_narrator",
        "energetic_explainer",
        "deep_documentary",
        "warm_storyteller",
        "mysterious_lowkey",
    }
    assert data["duration_target_s"] == 50
    assert data["narration"] == narration_fixture["narration"]
    assert len(data["scenes"]) == 4
    assert data["youtube"]["title"] == "Espresso at Dawn"
    assert "prompt_params" in data
    assert data["prompt_params"]["seed"] == 42


@pytest.mark.asyncio
async def test_script_agent_computes_scene_timings_from_word_counts(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)

    result = await agent.run(_ctx(tmp_path))
    data = json.loads(result.artifacts["script.json"].read_text())

    scenes = data["scenes"]
    # Scenes must be contiguous: scene[i].end_s == scene[i+1].start_s
    for i in range(len(scenes) - 1):
        assert scenes[i]["end_s"] == pytest.approx(scenes[i + 1]["start_s"])
    # First scene starts at 0
    assert scenes[0]["start_s"] == 0.0
    # Last scene ends near duration_target_s
    assert scenes[-1]["end_s"] == pytest.approx(data["duration_target_s"], abs=0.01)
    # Each scene has visual_prompt and pexels_query merged in
    for sc in scenes:
        assert "visual_prompt" in sc
        assert "image_prompt" in sc
        assert "pexels_query" in sc


@pytest.mark.asyncio
async def test_script_agent_retries_on_word_count_out_of_tolerance(
    tmp_path: Path,
    scene_visuals_fixture: dict[str, Any],
) -> None:
    too_short = {
        "narration": "Two words only.",
        "scene_breaks": [{"index": 0, "narration_excerpt": "Two words only."}],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    ok = {
        "narration": " ".join(["word"] * 125),
        "scene_breaks": [
            {"index": 0, "narration_excerpt": " ".join(["word"] * 63)},
            {"index": 1, "narration_excerpt": " ".join(["word"] * 62)},
        ],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([too_short, ok, scene_visuals_fixture])
    # Only ok narration fits the default tolerance
    agent = ScriptAgent(gemini=fake)

    await agent.run(_ctx(tmp_path))

    # Two narration prompts (first failed length check, second OK) + one visuals prompt = 3 total
    assert len(fake.prompts) == 3


@pytest.mark.asyncio
async def test_script_agent_fails_after_max_length_retries(
    tmp_path: Path,
) -> None:
    too_short = {
        "narration": "Tiny.",
        "scene_breaks": [{"index": 0, "narration_excerpt": "Tiny."}],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([too_short, too_short, too_short])
    agent = ScriptAgent(gemini=fake, max_length_retries=2)

    with pytest.raises(ValueError, match="word count"):
        await agent.run(_ctx(tmp_path))


@pytest.mark.asyncio
async def test_script_agent_fails_fast_on_zero_scenes(tmp_path: Path) -> None:
    bad = {
        "narration": " ".join(["word"] * 120),
        "scene_breaks": [],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([bad])
    agent = ScriptAgent(gemini=fake)

    with pytest.raises(ValueError, match="scenes"):
        await agent.run(_ctx(tmp_path))


@pytest.mark.asyncio
async def test_script_agent_metadata_includes_voice_category_and_params(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)

    result = await agent.run(_ctx(tmp_path))

    assert "voice_category" in result.metadata
    assert "duration_target_s" in result.metadata
    assert "prompt_params" in result.metadata
    assert result.metadata["prompt_params"]["seed"] == 42


@pytest.mark.asyncio
async def test_script_json_has_image_prompt_and_video_style(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)
    result = await agent.run(_ctx(tmp_path))
    data = json.loads(result.artifacts["script.json"].read_text())

    assert data["video_style"] == scene_visuals_fixture["video_style"]
    for scene in data["scenes"]:
        assert isinstance(scene["image_prompt"], str)
        assert len(scene["image_prompt"]) > 0
