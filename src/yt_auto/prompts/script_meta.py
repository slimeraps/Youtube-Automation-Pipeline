"""Pools of story-shape parameters + the seeded picker used by the Script Agent.

Same topic, same seed → same parameter choices → reproducible run.
Same topic, different seed → different video.
"""
import random
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Literal

VideoFormat = Literal["long", "short"]

TONES: tuple[str, ...] = (
    "contemplative",
    "urgent",
    "playful",
    "ominous",
    "wonder-struck",
    "deadpan",
    "warm-mentor",
    "investigative",
)

STRUCTURES: tuple[str, ...] = (
    "three_act",
    "list_countdown",
    "chronological_journey",
    "question_then_answer",
    "myth_vs_reality",
    "zoom_in_zoom_out",
)

NARRATIVE_STYLES: tuple[str, ...] = (
    "second_person_immersive",
    "third_person_omniscient",
    "first_person_observer",
    "documentary_clinical",
    "campfire_storyteller",
)

HOOK_STYLES: tuple[str, ...] = (
    "cold_open_question",
    "shocking_statistic",
    "in_medias_res_scene",
    "contrarian_claim",
    "paradox",
)

VOICE_CATEGORIES: tuple[str, ...] = (
    "calm_narrator",
    "energetic_explainer",
    "deep_documentary",
    "warm_storyteller",
    "mysterious_lowkey",
)

# tone -> (preferred voices, weight bias for preferred).
# Anything not in preferred is picked uniformly from the rest.
_TONE_VOICE_BIAS: dict[str, tuple[tuple[str, ...], float]] = {
    "ominous": (("deep_documentary", "mysterious_lowkey"), 0.7),
    "urgent": (("energetic_explainer", "deep_documentary"), 0.65),
    "playful": (("energetic_explainer", "warm_storyteller"), 0.65),
    "contemplative": (("calm_narrator", "warm_storyteller"), 0.65),
    "wonder-struck": (("warm_storyteller", "calm_narrator"), 0.6),
    "deadpan": (("calm_narrator", "mysterious_lowkey"), 0.6),
    "warm-mentor": (("warm_storyteller", "calm_narrator"), 0.7),
    "investigative": (("deep_documentary", "mysterious_lowkey"), 0.65),
}

# Words-per-second target by voice category (used for length math).
_WPS_BY_CATEGORY: dict[str, float] = {
    "calm_narrator": 2.3,
    "energetic_explainer": 2.7,
    "deep_documentary": 2.2,
    "warm_storyteller": 2.4,
    "mysterious_lowkey": 2.1,
}

DEFAULT_WPS = 2.4

_DURATION_BY_FORMAT: dict[VideoFormat, int] = {"long": 600, "short": 50}


@dataclass(frozen=True)
class PromptParams:
    tone: str
    structure: str
    narrative_style: str
    hook_style: str
    voice_category: str
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick_voice_for_tone(rng: random.Random, tone: str) -> str:
    bias = _TONE_VOICE_BIAS.get(tone)
    if bias is None:
        return rng.choice(VOICE_CATEGORIES)
    preferred, weight = bias
    if rng.random() < weight:
        return rng.choice(preferred)
    rest = tuple(v for v in VOICE_CATEGORIES if v not in preferred)
    return rng.choice(rest)


def build_params(topic: str, video_format: VideoFormat, seed: int | None) -> PromptParams:
    """Pick a tone/structure/etc. tuple. Determined entirely by seed if provided."""
    if seed is None:
        seed = secrets.randbits(63)
    rng = random.Random(seed)
    tone = rng.choice(TONES)
    return PromptParams(
        tone=tone,
        structure=rng.choice(STRUCTURES),
        narrative_style=rng.choice(NARRATIVE_STYLES),
        hook_style=rng.choice(HOOK_STYLES),
        voice_category=_pick_voice_for_tone(rng, tone),
        seed=seed,
    )


def target_duration_seconds(video_format: VideoFormat) -> int:
    return _DURATION_BY_FORMAT[video_format]


def wps_for_voice(voice_category: str) -> float:
    return _WPS_BY_CATEGORY.get(voice_category, DEFAULT_WPS)


def target_word_count(video_format: VideoFormat, voice_category: str | None = None) -> int:
    wps = wps_for_voice(voice_category) if voice_category else DEFAULT_WPS
    return int(target_duration_seconds(video_format) * wps)


from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(
    loader=PackageLoader("yt_auto.prompts", "templates"),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_narration_prompt(
    topic: str,
    video_format: VideoFormat,
    params: PromptParams,
    word_target: int,
) -> str:
    tmpl = _env.get_template("narration.j2")
    return tmpl.render(
        topic=topic,
        video_format=video_format,
        params=params,
        word_target=word_target,
    )


def render_scene_visuals_prompt(scenes: list[dict[str, Any]]) -> str:
    tmpl = _env.get_template("scene_visuals.j2")
    return tmpl.render(scenes=scenes)
