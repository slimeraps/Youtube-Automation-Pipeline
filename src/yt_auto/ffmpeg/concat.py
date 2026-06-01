"""Concatenate pre-prepared clips into one silent output file using the ffmpeg
concat demuxer. All input clips MUST already share codec, fps, resolution
(use prepare_clip first)."""

import asyncio
from pathlib import Path

from yt_auto.ffmpeg.prepare_clip import FFmpegError


async def concat_clips(*, clips: list[Path], dest: Path) -> None:
    if not clips:
        raise ValueError("concat_clips needs at least one clip")

    # The concat demuxer takes a text manifest of `file '<path>'` lines.
    # ffmpeg resolves relative paths inside the manifest against the manifest's
    # own directory, not the process CWD — so absolute paths are required when
    # the manifest and the clips both live under a relative output directory.
    manifest = dest.with_suffix(".concat.txt")
    manifest.write_text(
        "\n".join(f"file '{c.resolve().as_posix()}'" for c in clips),
        encoding="utf-8",
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            str(dest),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise FFmpegError(
                f"concat failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()[-500:]}"
            )
    finally:
        manifest.unlink(missing_ok=True)
