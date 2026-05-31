from collections import Counter

import pytest

from yt_auto.prompts.script_meta import (
    HOOK_STYLES,
    NARRATIVE_STYLES,
    STRUCTURES,
    TONES,
    VOICE_CATEGORIES,
    build_params,
    target_duration_seconds,
    target_word_count,
)


def test_build_params_is_deterministic_for_same_seed() -> None:
    a = build_params(topic="x", video_format="long", seed=42)
    b = build_params(topic="x", video_format="long", seed=42)
    assert a == b


def test_build_params_returns_values_from_pools() -> None:
    p = build_params(topic="x", video_format="long", seed=1)
    assert p.tone in TONES
    assert p.structure in STRUCTURES
    assert p.narrative_style in NARRATIVE_STYLES
    assert p.hook_style in HOOK_STYLES
    assert p.voice_category in VOICE_CATEGORIES


def test_build_params_with_no_seed_generates_random_seed() -> None:
    p = build_params(topic="x", video_format="long", seed=None)
    assert isinstance(p.seed, int)
    assert p.seed >= 0


def test_all_pool_options_are_reachable_across_many_seeds() -> None:
    tones_seen: set[str] = set()
    structures_seen: set[str] = set()
    for seed in range(500):
        p = build_params(topic="x", video_format="long", seed=seed)
        tones_seen.add(p.tone)
        structures_seen.add(p.structure)
    assert tones_seen == set(TONES)
    assert structures_seen == set(STRUCTURES)


def test_ominous_tone_biases_toward_deep_or_mysterious_voice() -> None:
    voice_counts: Counter[str] = Counter()
    for seed in range(2000):
        p = build_params(topic="x", video_format="long", seed=seed)
        if p.tone == "ominous":
            voice_counts[p.voice_category] += 1

    total = sum(voice_counts.values())
    assert total > 0, "ominous tone should appear in 2000 seeds"
    matching = voice_counts["deep_documentary"] + voice_counts["mysterious_lowkey"]
    assert matching / total >= 0.55, f"expected >=55%, got {matching/total:.0%}"


@pytest.mark.parametrize(
    "fmt,expected",
    [("long", 600), ("short", 50)],
)
def test_target_duration_seconds(fmt: str, expected: int) -> None:
    assert target_duration_seconds(fmt) == expected  # type: ignore[arg-type]


def test_target_word_count_uses_default_wps() -> None:
    # 600s * 2.4 wps = 1440
    assert target_word_count("long") == 1440
    # 50s * 2.4 wps = 120
    assert target_word_count("short") == 120


def test_prompt_params_to_dict_round_trip() -> None:
    p = build_params(topic="x", video_format="long", seed=7)
    d = p.to_dict()
    assert d["tone"] == p.tone
    assert d["seed"] == p.seed
