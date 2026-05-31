from yt_auto.prompts.script_meta import (
    build_params,
    render_narration_prompt,
    render_scene_visuals_prompt,
    target_word_count,
)


def test_render_narration_prompt_includes_all_params() -> None:
    params = build_params(topic="the history of espresso", video_format="short", seed=1)
    prompt = render_narration_prompt(
        topic="the history of espresso",
        video_format="short",
        params=params,
        word_target=target_word_count("short", params.voice_category),
    )

    assert "the history of espresso" in prompt
    assert params.tone in prompt
    assert params.structure in prompt
    assert params.narrative_style in prompt
    assert params.hook_style in prompt
    assert "JSON" in prompt
    assert "narration" in prompt
    assert "scene_breaks" in prompt
    assert "youtube" in prompt
    # Word target must appear so the model sees it
    assert str(target_word_count("short", params.voice_category)) in prompt


def test_render_scene_visuals_prompt_serializes_scene_list() -> None:
    scenes = [
        {"index": 0, "narration_excerpt": "a curious traveler arrives"},
        {"index": 1, "narration_excerpt": "the city wakes at dawn"},
    ]
    prompt = render_scene_visuals_prompt(scenes=scenes)

    assert "a curious traveler arrives" in prompt
    assert "the city wakes at dawn" in prompt
    assert "visual_prompt" in prompt
    assert "pexels_query" in prompt
    assert "JSON" in prompt
