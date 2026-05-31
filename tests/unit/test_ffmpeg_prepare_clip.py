import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.ffmpeg.probe import probe_duration_s


def _make_test_video(path: Path, seconds: float, width: int, height: int) -> None:
    """Generate a solid-color test video at given duration + dimensions."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:size={width}x{height}:duration={seconds}:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_prepare_clip_trims_when_source_longer_than_target(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    out = tmp_path / "out.mp4"
    _make_test_video(src, seconds=10.0, width=1920, height=1080)

    await prepare_clip(src=src, dest=out, target_duration_s=4.0, width=1920, height=1080, fps=30)

    duration = await probe_duration_s(out)
    assert duration == pytest.approx(4.0, abs=0.2)


@pytest.mark.asyncio
async def test_prepare_clip_loops_when_source_shorter_than_target(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    out = tmp_path / "out.mp4"
    _make_test_video(src, seconds=2.0, width=1920, height=1080)

    await prepare_clip(src=src, dest=out, target_duration_s=7.0, width=1920, height=1080, fps=30)

    duration = await probe_duration_s(out)
    assert duration == pytest.approx(7.0, abs=0.2)


@pytest.mark.asyncio
async def test_prepare_clip_scales_to_target_dimensions(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    out = tmp_path / "out.mp4"
    # Source is 1280x720, target 1920x1080
    _make_test_video(src, seconds=5.0, width=1280, height=720)

    await prepare_clip(src=src, dest=out, target_duration_s=5.0, width=1920, height=1080, fps=30)

    # Probe the output dimensions
    import json

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(result.stdout)["streams"][0]
    assert streams["width"] == 1920
    assert streams["height"] == 1080
