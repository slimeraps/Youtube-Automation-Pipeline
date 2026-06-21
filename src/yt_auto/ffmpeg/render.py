"""Mux silent video + narration audio + burned-in subtitles into final mp4."""

import asyncio
from pathlib import Path

from yt_auto.ffmpeg.prepare_clip import FFmpegError

def _subtitle_style(width: int, height: int) -> str:
    # Tell libass the canvas is the real video resolution so FontSize and
    # margins are interpreted in actual pixels instead of libass's default
    # PlayResY=288 (which makes everything ~6x too large on a 1920-tall
    # vertical short).
    font_size = round(height * 0.029)  # ~56 on 1920, ~31 on 1080
    margin_v = round(height * 0.16)  # ~307 on 1920 — sits in the lower third
    margin_h = round(width * 0.07)  # ~76 on 1080
    # PrimaryColour is libass BGR: &H00BBGGRR. #FFB300 amber → 00B3FF.
    return (
        f"PlayResX={width},PlayResY={height},"
        "FontName=Arial,Bold=1,PrimaryColour=&H0000B3FF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=1,"
        f"FontSize={font_size},Alignment=2,"
        f"MarginV={margin_v},MarginL={margin_h},MarginR={margin_h}"
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
    # Scale BEFORE burning subtitles so libass sees the final canvas size.
    style = _subtitle_style(width, height)
    vf = f"scale={width}:{height},fps={fps},subtitles='{sub_path}':force_style='{style}'"

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
