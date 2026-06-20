"""Script Agent: builds script.json from topic + format using Gemini."""

import json
from typing import Any, Protocol

from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext
from yt_auto.prompts.script_meta import (
    PromptParams,
    build_params,
    render_narration_prompt,
    render_scene_visuals_prompt,
    target_duration_seconds,
    target_word_count,
)

log = get_logger(__name__)


class GeminiLike(Protocol):
    async def generate_json(self, prompt: str) -> dict[str, Any]: ...


class ScriptAgent:
    name = "script"

    def __init__(
        self,
        gemini: GeminiLike,
        *,
        word_count_tolerance: float = 0.10,
        max_length_retries: int = 2,
    ) -> None:
        self._gemini = gemini
        self._tolerance = word_count_tolerance
        self._max_length_retries = max_length_retries

    async def run(self, ctx: RunContext) -> StageResult:
        seed = ctx.metadata.get("seed")
        params = build_params(topic=ctx.topic, video_format=ctx.format, seed=seed)
        word_target = target_word_count(ctx.format, params.voice_category)

        narration_data = await self._generate_narration_with_length_check(
            ctx=ctx, params=params, word_target=word_target
        )

        scenes_timed = self._compute_scene_timings(
            scene_breaks=narration_data["scene_breaks"],
            narration=narration_data["narration"],
            duration_s=target_duration_seconds(ctx.format),
        )

        visuals_data = await self._gemini.generate_json(
            render_scene_visuals_prompt(scenes=scenes_timed)
        )
        scenes_with_visuals = self._merge_visuals(scenes_timed, visuals_data["scenes"])
        video_style = visuals_data.get("video_style", "")

        script = {
            "topic": ctx.topic,
            "format": ctx.format,
            "voice_category": params.voice_category,
            "duration_target_s": target_duration_seconds(ctx.format),
            "video_style": video_style,
            "narration": narration_data["narration"],
            "scenes": scenes_with_visuals,
            "youtube": narration_data["youtube"],
            "prompt_params": params.to_dict(),
        }

        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        script_path = ctx.run_dir / "script.json"
        script_path.write_text(json.dumps(script, indent=2))
        log.info("script_written", path=str(script_path), scenes=len(scenes_with_visuals))

        return StageResult(
            artifacts={"script.json": script_path},
            metadata={
                "duration_target_s": script["duration_target_s"],
                "voice_category": params.voice_category,
                "prompt_params": params.to_dict(),
            },
        )

    async def _generate_narration_with_length_check(
        self, *, ctx: RunContext, params: PromptParams, word_target: int
    ) -> dict[str, Any]:
        last_word_count = 0
        for attempt in range(1, self._max_length_retries + 2):  # initial + retries
            prompt = render_narration_prompt(
                topic=ctx.topic,
                video_format=ctx.format,
                params=params,
                word_target=word_target,
            )
            if attempt > 1:
                prompt += (
                    f"\n\nNOTE: your previous attempt was {last_word_count} words. "
                    f"Target is {word_target} (±{int(self._tolerance * 100)}%). "
                    "Adjust length accordingly."
                )
            data = await self._gemini.generate_json(prompt)
            self._validate_narration_shape(data)
            wc = self._word_count(data["narration"])
            if self._within_tolerance(wc, word_target):
                return data
            last_word_count = wc
            log.warning(
                "narration_length_off",
                attempt=attempt,
                got=wc,
                target=word_target,
                tolerance=self._tolerance,
            )
        raise ValueError(
            f"narration word count {last_word_count} stayed outside "
            f"±{int(self._tolerance * 100)}% of target {word_target} after "
            f"{self._max_length_retries} retries"
        )

    @staticmethod
    def _validate_narration_shape(data: dict[str, Any]) -> None:
        for key in ("narration", "scene_breaks", "youtube"):
            if key not in data:
                raise ValueError(f"narration response missing key: {key}")
        if not isinstance(data["scene_breaks"], list) or len(data["scene_breaks"]) == 0:
            raise ValueError("narration response has zero scenes")

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    def _within_tolerance(self, got: int, target: int) -> bool:
        lo = target * (1 - self._tolerance)
        hi = target * (1 + self._tolerance)
        return lo <= got <= hi

    @staticmethod
    def _compute_scene_timings(
        scene_breaks: list[dict[str, Any]],
        narration: str,
        duration_s: int,
    ) -> list[dict[str, Any]]:
        total_words = max(1, len(narration.split()))
        scenes: list[dict[str, Any]] = []
        cursor = 0.0
        for sb in scene_breaks:
            excerpt = sb["narration_excerpt"]
            wc = max(1, len(excerpt.split()))
            duration = duration_s * (wc / total_words)
            scenes.append(
                {
                    "index": sb["index"],
                    "start_s": round(cursor, 3),
                    "end_s": round(cursor + duration, 3),
                    "narration_excerpt": excerpt,
                }
            )
            cursor += duration
        # Snap last scene end_s exactly to duration_s to avoid float drift
        if scenes:
            scenes[-1]["end_s"] = float(duration_s)
        return scenes

    @staticmethod
    def _merge_visuals(
        timed: list[dict[str, Any]], visuals: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_index = {v["index"]: v for v in visuals}
        out: list[dict[str, Any]] = []
        for scene in timed:
            v = by_index.get(scene["index"])
            if v is None:
                raise ValueError(f"visuals response missing scene index {scene['index']}")
            out.append(
                {
                    **scene,
                    "visual_prompt": v["visual_prompt"],
                    "image_prompt": v["image_prompt"],
                    "pexels_query": v["pexels_query"],
                }
            )
        return out
