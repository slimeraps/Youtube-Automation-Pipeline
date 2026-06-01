"""Media Agent: search Pexels per scene, download, normalize, concat to silent video."""

import json
from pathlib import Path
from typing import Any, Literal, Protocol

from yt_auto.clients.pexels import Clip
from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

# Render dimensions for each format.
_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30


class MediaError(Exception):
    """Could not produce video_silent.mp4."""


class PexelsLike(Protocol):
    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]: ...
    async def download(self, *, url: str, dest: Path) -> None: ...


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
    # Snap last end exactly to target.
    rescaled[-1]["end_s"] = target_total_duration_s
    return rescaled


def pick_best_clip(clips: list[Clip], *, target_duration_s: float) -> Clip:
    if not clips:
        raise MediaError("no clips returned from Pexels for this scene")
    qualifying = [c for c in clips if c.duration_s >= target_duration_s]
    if qualifying:
        return min(qualifying, key=lambda c: c.duration_s)
    return max(clips, key=lambda c: c.duration_s)


class MediaAgent:
    name = "media"

    def __init__(self, pexels: PexelsLike, *, per_page: int = 10) -> None:
        self._pexels = pexels
        self._per_page = per_page

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        # Pipeline-full passes actual_duration_s via in-memory metadata. The per-agent
        # CLI rehydrates ctx from disk and loses that key, so probe voice.mp3 directly.
        actual_voice_duration = ctx.metadata.get("actual_duration_s")
        if actual_voice_duration is None:
            actual_voice_duration = await probe_duration_s(ctx.artifacts["voice.mp3"])
        scenes = rescale_scenes(script["scenes"], target_total_duration_s=actual_voice_duration)
        fmt: Literal["long", "short"] = script["format"]
        width, height = _DIMS_BY_FORMAT[fmt]

        footage_dir = ctx.run_dir / "footage"
        footage_dir.mkdir(parents=True, exist_ok=True)
        prepared_paths: list[Path] = []

        for scene in scenes:
            query: str = scene["pexels_query"]
            target = float(scene["end_s"] - scene["start_s"])
            clips = await self._pexels.search_videos(query=query, per_page=self._per_page)
            picked = pick_best_clip(clips, target_duration_s=target)

            raw_path = footage_dir / f"scene_{scene['index']:03d}_raw.mp4"
            prepared_path = footage_dir / f"scene_{scene['index']:03d}.mp4"
            await self._pexels.download(url=picked.url, dest=raw_path)
            await prepare_clip(
                src=raw_path,
                dest=prepared_path,
                target_duration_s=target,
                width=width,
                height=height,
                fps=_FPS,
            )
            prepared_paths.append(prepared_path)

        dest = ctx.run_dir / "video_silent.mp4"
        await concat_clips(clips=prepared_paths, dest=dest)
        log.info("media_done", path=str(dest), clips=len(prepared_paths))

        return StageResult(
            artifacts={"video_silent.mp4": dest},
            metadata={"clip_count": len(prepared_paths)},
        )
