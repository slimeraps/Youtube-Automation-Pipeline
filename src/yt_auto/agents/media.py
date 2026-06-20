"""Media Agent: produce a normalized clip per scene via pluggable SceneSources, then concat."""

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from yt_auto.agents.sources import SceneSource, SceneSourceError
from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30

# A primary may be a SceneSource directly, or a factory that takes the script's
# video_style and returns a SceneSource. The factory form lets LocalDiffusionSource
# bind to a style read from script.json at run time without leaking script state
# into the CLI wiring.
PrimaryArg = SceneSource | Callable[[str], SceneSource]


class MediaError(Exception):
    """Could not produce video_silent.mp4."""


def rescale_scenes(
    scenes: list[dict[str, Any]], *, target_total_duration_s: float
) -> list[dict[str, Any]]:
    if not scenes:
        raise MediaError("rescale_scenes needs at least one scene")
    original_total = scenes[-1]["end_s"] - scenes[0]["start_s"]
    if original_total <= 0:
        raise MediaError("scenes have zero total duration")
    factor = target_total_duration_s / original_total
    rescaled: list[dict[str, Any]] = []
    cursor = 0.0
    for sc in scenes:
        duration = (sc["end_s"] - sc["start_s"]) * factor
        rescaled.append({**sc, "start_s": cursor, "end_s": cursor + duration})
        cursor += duration
    rescaled[-1]["end_s"] = target_total_duration_s
    return rescaled


def _resolve_primary(arg: PrimaryArg, video_style: str) -> SceneSource:
    # A SceneSource has produce_clip; a factory is callable but lacks it.
    if hasattr(arg, "produce_clip"):
        return arg  # type: ignore[return-value]
    return arg(video_style)  # type: ignore[operator]


class MediaAgent:
    name = "media"

    def __init__(
        self,
        *,
        primary: PrimaryArg,
        fallback: SceneSource | None = None,
        primary_healthcheck: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._primary_arg = primary
        self._fallback = fallback
        self._primary_healthcheck = primary_healthcheck

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        video_style = script.get("video_style", "")
        primary = _resolve_primary(self._primary_arg, video_style)

        primary_healthy = True
        if self._primary_healthcheck is not None:
            primary_healthy = await self._primary_healthcheck()
            if not primary_healthy:
                log.warning("primary_source_unreachable_using_fallback")
                if self._fallback is None:
                    raise MediaError(
                        "primary healthcheck failed and no fallback configured"
                    )

        actual_voice_duration = ctx.metadata.get("actual_duration_s")
        if actual_voice_duration is None:
            actual_voice_duration = await probe_duration_s(ctx.artifacts["voice.mp3"])
        scenes = rescale_scenes(script["scenes"], target_total_duration_s=actual_voice_duration)
        fmt: Literal["long", "short"] = script["format"]
        width, height = _DIMS_BY_FORMAT[fmt]

        footage_dir = ctx.run_dir / "footage"
        footage_dir.mkdir(parents=True, exist_ok=True)
        prepared_paths: list[Path] = []
        counts = {"primary": 0, "fallback": 0}

        for scene in scenes:
            target = float(scene["end_s"] - scene["start_s"])
            dest = footage_dir / f"scene_{scene['index']:03d}.mp4"

            if not primary_healthy:
                # Whole-run downgrade: use fallback directly, skip primary.
                try:
                    await self._fallback.produce_clip(  # type: ignore[union-attr]
                        scene=scene,
                        target_duration_s=target,
                        width=width,
                        height=height,
                        fps=_FPS,
                        dest=dest,
                    )
                    counts["fallback"] += 1
                except SceneSourceError as exc:
                    raise MediaError(
                        f"fallback failed on scene {scene['index']} (primary already skipped): {exc}"
                    ) from exc
                prepared_paths.append(dest)
                continue

            try:
                await primary.produce_clip(
                    scene=scene,
                    target_duration_s=target,
                    width=width,
                    height=height,
                    fps=_FPS,
                    dest=dest,
                )
                counts["primary"] += 1
            except SceneSourceError as exc:
                log.warning(
                    "primary_source_failed",
                    scene_index=scene["index"],
                    error=str(exc),
                )
                if self._fallback is None:
                    raise MediaError(
                        f"primary failed on scene {scene['index']} and no fallback configured: {exc}"
                    ) from exc
                try:
                    await self._fallback.produce_clip(
                        scene=scene,
                        target_duration_s=target,
                        width=width,
                        height=height,
                        fps=_FPS,
                        dest=dest,
                    )
                    counts["fallback"] += 1
                except SceneSourceError as exc2:
                    raise MediaError(
                        f"both sources failed on scene {scene['index']}: "
                        f"primary={exc}; fallback={exc2}"
                    ) from exc2

            prepared_paths.append(dest)

        dest_video = ctx.run_dir / "video_silent.mp4"
        await concat_clips(clips=prepared_paths, dest=dest_video)
        log.info(
            "media_done",
            path=str(dest_video),
            clips=len(prepared_paths),
            source_counts=counts,
        )

        return StageResult(
            artifacts={"video_silent.mp4": dest_video},
            metadata={
                "clip_count": len(prepared_paths),
                "source_counts": counts,
                "primary_healthy": primary_healthy,
            },
        )
