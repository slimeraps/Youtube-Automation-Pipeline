"""Tests for the Ken Burns still→clip helper. Uses real ffmpeg."""

import shutil
from pathlib import Path

import pytest

from yt_auto.ffmpeg.ken_burns import MOTION_PRESETS, pick_motion, still_to_clip
from yt_auto.ffmpeg.probe import probe_duration_s

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_STILL = FIXTURE_DIR / "sample_still.png"


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_pick_motion_deterministic_for_same_seed() -> None:
    assert pick_motion(42) == pick_motion(42)


def test_pick_motion_returns_known_preset() -> None:
    assert pick_motion(0) in MOTION_PRESETS


@pytest.mark.asyncio
async def test_still_to_clip_produces_target_duration(tmp_path: Path) -> None:
    dest = tmp_path / "clip.mp4"
    await still_to_clip(
        src=SAMPLE_STILL,
        dest=dest,
        duration_s=2.5,
        width=1920,
        height=1080,
        fps=30,
        seed=1,
    )
    assert dest.exists()
    duration = await probe_duration_s(dest)
    assert duration == pytest.approx(2.5, abs=0.1)


@pytest.mark.asyncio
async def test_still_to_clip_works_for_portrait(tmp_path: Path) -> None:
    dest = tmp_path / "clip.mp4"
    await still_to_clip(
        src=SAMPLE_STILL,
        dest=dest,
        duration_s=1.5,
        width=1080,
        height=1920,
        fps=30,
        seed=2,
    )
    assert dest.exists()
    duration = await probe_duration_s(dest)
    assert duration == pytest.approx(1.5, abs=0.1)


@pytest.mark.asyncio
async def test_still_to_clip_each_preset_renders(tmp_path: Path) -> None:
    for i, _ in enumerate(MOTION_PRESETS):
        dest = tmp_path / f"clip_{i}.mp4"
        await still_to_clip(
            src=SAMPLE_STILL,
            dest=dest,
            duration_s=1.0,
            width=1280,
            height=720,
            fps=30,
            seed=i,
        )
        assert dest.exists()
        assert dest.stat().st_size > 0
