"""Pluggable per-scene clip producers used by MediaAgent.

Each SceneSource takes a scene dict + target dims/duration and writes a
normalized .mp4 to `dest`. Any failure raises SceneSourceError; the agent
catches that and tries the next source in line.
"""

from pathlib import Path
from typing import Any, Protocol

from yt_auto.clients.comfyui import ComfyUIClient, ComfyUIError
from yt_auto.clients.pexels import Clip
from yt_auto.ffmpeg.ken_burns import still_to_clip
from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.logging import get_logger

log = get_logger(__name__)

# SDXL-native generation dimensions, chosen to match output aspect ratio.
# Anything close to 1024x1024 area; these are the standard SDXL ratios.
_GEN_DIMS_LANDSCAPE = (1344, 768)
_GEN_DIMS_PORTRAIT = (768, 1344)


class SceneSourceError(Exception):
    """A per-scene clip producer could not produce a clip."""


class PexelsLike(Protocol):
    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]: ...
    async def download(self, *, url: str, dest: Path) -> None: ...


class ComfyLike(Protocol):
    async def generate_image(
        self, *, prompt: str, width: int, height: int, seed: int, dest: Path
    ) -> None: ...


class SceneSource(Protocol):
    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None: ...


def _pick_best_clip(clips: list[Clip], *, target_duration_s: float) -> Clip:
    if not clips:
        raise SceneSourceError("no clips returned from Pexels for this scene")
    qualifying = [c for c in clips if c.duration_s >= target_duration_s]
    if qualifying:
        return min(qualifying, key=lambda c: c.duration_s)
    return max(clips, key=lambda c: c.duration_s)


class PexelsSource:
    """Search Pexels for the scene's pexels_query, pick best clip, normalize."""

    def __init__(self, pexels: PexelsLike, *, per_page: int = 10) -> None:
        self._pexels = pexels
        self._per_page = per_page

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        query: str = scene["pexels_query"]
        try:
            clips = await self._pexels.search_videos(query=query, per_page=self._per_page)
            picked = _pick_best_clip(clips, target_duration_s=target_duration_s)
            raw_path = dest.with_name(dest.stem + "_raw.mp4")
            await self._pexels.download(url=picked.url, dest=raw_path)
            await prepare_clip(
                src=raw_path,
                dest=dest,
                target_duration_s=target_duration_s,
                width=width,
                height=height,
                fps=fps,
            )
        except SceneSourceError:
            raise
        except Exception as exc:  # noqa: BLE001 — translate any I/O / ffmpeg failure
            raise SceneSourceError(f"pexels source failed: {exc}") from exc


class LocalDiffusionSource:
    """Generate a still via ComfyUI, then animate it with Ken Burns."""

    def __init__(self, comfyui: ComfyLike, *, video_style: str) -> None:
        self._comfyui = comfyui
        self._video_style = video_style

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        image_prompt = scene["image_prompt"]
        full_prompt = f"{image_prompt}, {self._video_style}"
        gen_w, gen_h = _GEN_DIMS_LANDSCAPE if width >= height else _GEN_DIMS_PORTRAIT
        seed = int(scene["index"])
        png_path = dest.with_name(dest.stem + ".png")
        try:
            await self._comfyui.generate_image(
                prompt=full_prompt, width=gen_w, height=gen_h, seed=seed, dest=png_path
            )
            await still_to_clip(
                src=png_path,
                dest=dest,
                duration_s=target_duration_s,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
            )
        except ComfyUIError as exc:
            raise SceneSourceError(f"comfyui generation failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise SceneSourceError(f"local diffusion failed: {exc}") from exc


# Ensure ComfyUIClient stays importable from this module for callers / type tools.
__all__ = [
    "ComfyLike",
    "ComfyUIClient",
    "LocalDiffusionSource",
    "PexelsLike",
    "PexelsSource",
    "SceneSource",
    "SceneSourceError",
]
