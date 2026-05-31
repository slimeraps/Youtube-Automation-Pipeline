"""Mux silent video + narration audio + burned-in subtitles into final mp4."""

import asyncio
from pathlib import Path

from yt_auto.ffmpeg.prepare_clip import FFmpegError

# libass style for captions: white bold sans-serif, black outline + shadow,
# centered horizontally, sitting ~12% up from the bottom.
_SUBTITLE_STYLE = (
    "FontName=Arial,FontSize=36,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,"
    "Alignment=2,MarginV=120"
)


def _escape_subtitle_path(p: Path) -> str:
    """ffmpeg's subtitles filter uses ':' as an arg separator, so colons in
    Windows paths must be escaped. Forward slashes are accepted on Windows."""
    posix = p.as_posix()
    return posix.replace(":", r"\:")


async def render_final(
    *,
    video: Path,
    audio: Path,
    subtitles: Path,
    dest: Path,
    width: int,
    height: int,
    video_bitrate: str = "8M",
    audio_bitrate: str = "192k",
    fps: int = 30,
) -> None:
    """Encode the final mp4 with burned-in subtitles and AAC audio."""
    sub_path = _escape_subtitle_path(subtitles)
    vf = f"subtitles='{sub_path}':force_style='{_SUBTITLE_STYLE}',scale={width}:{height},fps={fps}"

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-b:v",
        video_bitrate,
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-shortest",  # stop when narration ends
        "-movflags",
        "+faststart",  # YouTube/web playback
        str(dest),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(
            f"render_final failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()[-800:]}"
        )
