"""Async wrapper around `ffprobe` for reading media duration."""

import asyncio
import json
from pathlib import Path


class FFprobeError(Exception):
    """ffprobe exited non-zero or produced unparseable output."""


async def probe_duration_s(path: Path) -> float:
    """Return the duration of an audio or video file in seconds."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FFprobeError(
            f"ffprobe failed for {path} (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()}"
        )
    try:
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise FFprobeError(f"could not parse ffprobe output for {path}: {e}") from e
