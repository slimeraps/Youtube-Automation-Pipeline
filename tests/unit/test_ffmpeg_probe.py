"""These tests shell out to real ffmpeg/ffprobe. They're fast (<2s) but require
ffmpeg on PATH. Skip with -k 'not ffmpeg' if you don't have it yet."""

import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.probe import probe_duration_s


def _make_silent_wav(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=22050",
            "-t",
            str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.asyncio
async def test_probe_duration_returns_seconds_as_float(tmp_path: Path) -> None:
    wav = tmp_path / "silence.wav"
    _make_silent_wav(wav, 2.5)

    duration = await probe_duration_s(wav)

    assert isinstance(duration, float)
    assert duration == pytest.approx(2.5, abs=0.1)


@pytest.mark.asyncio
async def test_probe_duration_missing_file_raises(tmp_path: Path) -> None:
    from yt_auto.ffmpeg.probe import FFprobeError

    with pytest.raises(FFprobeError):
        await probe_duration_s(tmp_path / "no_such_file.mp3")
