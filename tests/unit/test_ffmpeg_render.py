import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.ffmpeg.render import render_final

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_silent_video(path: Path, seconds: float, width: int = 1920, height: int = 1080) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=green:size={width}x{height}:duration={seconds}:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


def _make_audio(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True,
    )


@pytest.mark.asyncio
async def test_render_final_produces_mp4_with_audio_and_burned_subs(tmp_path: Path) -> None:
    video = tmp_path / "silent.mp4"
    audio = tmp_path / "narration.mp3"
    srt = tmp_path / "captions.srt"
    out = tmp_path / "final.mp4"

    _make_silent_video(video, seconds=4.0)
    _make_audio(audio, seconds=4.0)
    srt.write_text((FIXTURES / "sample.srt").read_text(), encoding="utf-8")

    await render_final(
        video=video, audio=audio, subtitles=srt, dest=out,
        width=1920, height=1080, video_bitrate="8M", audio_bitrate="192k", fps=30,
    )

    assert out.exists()
    duration = await probe_duration_s(out)
    assert duration == pytest.approx(4.0, abs=0.3)

    # Confirm the output has both a video and an audio stream.
    import json
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
