import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.probe import probe_duration_s


def _make_test_video(path: Path, seconds: float, width: int = 1920, height: int = 1080) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:size={width}x{height}:duration={seconds}:rate=30",
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
async def test_concat_clips_joins_in_order(tmp_path: Path) -> None:
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    c = tmp_path / "c.mp4"
    out = tmp_path / "out.mp4"
    _make_test_video(a, 1.0)
    _make_test_video(b, 2.0)
    _make_test_video(c, 1.5)

    await concat_clips(clips=[a, b, c], dest=out)

    duration = await probe_duration_s(out)
    assert duration == pytest.approx(4.5, abs=0.2)


@pytest.mark.asyncio
async def test_concat_clips_empty_list_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one clip"):
        await concat_clips(clips=[], dest=tmp_path / "out.mp4")
