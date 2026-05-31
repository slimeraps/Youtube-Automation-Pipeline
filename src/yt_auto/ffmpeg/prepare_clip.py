"""Trim or loop a single source clip to an exact target duration and scale/crop
to target dimensions. Output is always silent H.264."""

import asyncio
from pathlib import Path

from yt_auto.ffmpeg.probe import probe_duration_s


class FFmpegError(Exception):
    """ffmpeg invocation failed."""


async def prepare_clip(
    *,
    src: Path,
    dest: Path,
    target_duration_s: float,
    width: int,
    height: int,
    fps: int,
) -> None:
    """Normalize one source clip to exact target duration + dimensions.

    If the source is longer than the target, trim from the start.
    If shorter, loop it (whole repeats + truncated tail) to fill.
    Either way, the output is exactly `target_duration_s` long at width x height
    with the input scaled-and-cropped to fit (no letterboxing).
    """
    src_duration = await probe_duration_s(src)

    # Scale + center-crop filter that preserves aspect ratio.
    #   scale to cover, then crop to exact target dims.
    vf = (
        f"scale='if(gt(a,{width}/{height}),-2,{width})':"
        f"'if(gt(a,{width}/{height}),{height},-2)',"
        f"crop={width}:{height},setsar=1,fps={fps}"
    )

    args: list[str] = ["ffmpeg", "-y"]
    if src_duration < target_duration_s:
        # Loop the file enough times to cover, then -t truncates.
        loops_needed = int(target_duration_s // src_duration) + 1
        args += ["-stream_loop", str(loops_needed)]
    args += [
        "-i",
        str(src),
        "-t",
        f"{target_duration_s:.3f}",
        "-vf",
        vf,
        "-an",  # strip audio (we add narration later)
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
            f"prepare_clip failed for {src} (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()[-500:]}"
        )
