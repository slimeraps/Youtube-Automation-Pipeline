"""Render a still image into a video clip with a slow ffmpeg zoompan motion."""

import asyncio
from pathlib import Path
from typing import Literal

from yt_auto.ffmpeg.prepare_clip import FFmpegError

Motion = Literal["zoom_in", "zoom_out", "pan_left", "pan_right"]
MOTION_PRESETS: tuple[Motion, ...] = ("zoom_in", "zoom_out", "pan_left", "pan_right")


def pick_motion(seed: int) -> Motion:
    return MOTION_PRESETS[seed % len(MOTION_PRESETS)]


def _build_zoompan_filter(
    *, motion: Motion, total_frames: int, width: int, height: int
) -> str:
    z_start = 1.0
    z_end = 1.15
    if motion == "zoom_in":
        z = f"{z_start}+({z_end - z_start})*on/{max(total_frames - 1, 1)}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "zoom_out":
        z = f"{z_end}-({z_end - z_start})*on/{max(total_frames - 1, 1)}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        z = str(z_end)
        x = f"(iw-iw/zoom)*(1-on/{max(total_frames - 1, 1)})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z = str(z_end)
        x = f"(iw-iw/zoom)*on/{max(total_frames - 1, 1)}"
        y = "ih/2-(ih/zoom/2)"
    else:
        raise AssertionError(f"unknown motion {motion}")
    return (
        f"scale=8000:-2,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:fps={total_frames}:s={width}x{height}"
    )


async def still_to_clip(
    *,
    src: Path,
    dest: Path,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    seed: int,
) -> None:
    """Render `src` as a `duration_s` clip at `width`x`height`@`fps` with motion."""
    motion = pick_motion(seed)
    total_frames = max(int(round(duration_s * fps)), 1)
    vf = _build_zoompan_filter(
        motion=motion, total_frames=total_frames, width=width, height=height
    )
    vf_full = f"{vf},fps={fps},setsar=1,format=yuv420p"

    args: list[str] = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(src),
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        vf_full,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "20",
        str(dest),
    ]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(
            f"still_to_clip failed for {src} (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()[-500:]}"
        )
