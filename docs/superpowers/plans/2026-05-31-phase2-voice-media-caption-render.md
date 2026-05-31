# Phase 2 — Voice + Caption + Media + Render Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four remaining content-producing agents (Voice, Caption, Media, Render) plus their CLI subcommands, so the pipeline can take a `script.json` from Phase 1 and produce a `final.mp4` end-to-end locally — no FastAPI, no Upload Agent yet (Phase 3).

**Architecture:** Each agent matches the same `Agent` protocol from Phase 1. ffmpeg is invoked via `asyncio.create_subprocess_exec` through a tiny wrapper module so agents stay shell-free. External APIs (ElevenLabs, Pexels) are wrapped behind thin clients with fake-friendly constructors. faster-whisper runs locally on CPU. Each agent is callable standalone via a new CLI subcommand (`voice <run-id>`, `caption <run-id>`, etc.), and a new `pipeline-local <topic>` subcommand chains all five stages off disk.

**Tech Stack:** `elevenlabs` (sync SDK wrapped in `asyncio.to_thread`), `faster-whisper`, `httpx` (Pexels, already installed), system `ffmpeg` / `ffprobe` binaries.

**Spec reference:** [docs/superpowers/specs/2026-05-30-youtube-automation-pipeline-design.md](../specs/2026-05-30-youtube-automation-pipeline-design.md) §5 stage I/O table (rows 2–5) and §14 phase boundary.

**Phase 2 decisions locked in during brainstorming:**
- Media Agent: for each scene, request top 10 Pexels clips, pick shortest ≥ scene duration; if all shorter, pick longest and loop via `-stream_loop`.
- Captions: burned-in via ffmpeg `subtitles` filter (libass), white bold sans-serif with black outline + shadow, center-bottom; sidecar `captions.srt` also kept.
- ElevenLabs model: `eleven_multilingual_v2` (broadly available, stable). Voice category → voice_id mapping read from `.env`.
- Render: H.264 + AAC, 8 Mbps video / 192 kbps audio, 30 fps, `+faststart` for YouTube. 1920x1080 for `long`, 1080x1920 for `short`.
- Voice produces real `.mp3`, Media rescales scene timings to match actual mp3 duration (the spec's "proportional rescale").
- Run-state rehydration: per-agent CLI subcommands accept a `<run-id>` and reconstruct `RunContext` by reading prior artifacts from disk (`script.json`, `voice.mp3`).

**Environment note:** The shell on this machine does not have `uv` on PATH. All commands below use `& "$env:USERPROFILE\.local\bin\uv.exe"` in PowerShell. If running in bash, substitute `~/.local/bin/uv.exe`.

**ffmpeg prerequisite:** `ffmpeg` and `ffprobe` must be on PATH. Verify with `ffmpeg -version` before starting Task 2. On Windows: install with `winget install ffmpeg` or download from gyan.dev.

---

## Task 1 — Extend Settings + `.env.example` for Phase 2

**Files:**
- Modify: `src/yt_auto/config.py`
- Modify: `.env.example`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Append the new keys to `.env.example`**

Replace the contents of `.env.example` with:

```
# --- LLM ---
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- Voice (ElevenLabs) ---
ELEVENLABS_API_KEY=
ELEVENLABS_MODEL=eleven_multilingual_v2
# voice_id pool keyed by category. Browse voices at https://elevenlabs.io/voice-library.
ELEVENLABS_VOICE_CALM_NARRATOR=
ELEVENLABS_VOICE_ENERGETIC_EXPLAINER=
ELEVENLABS_VOICE_DEEP_DOCUMENTARY=
ELEVENLABS_VOICE_WARM_STORYTELLER=
ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY=

# --- Footage (Pexels) ---
PEXELS_API_KEY=
PEXELS_PER_PAGE=10

# --- Captions (faster-whisper, local) ---
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# --- App ---
DATA_DIR=./data
OUTPUTS_DIR=./outputs
LOG_LEVEL=INFO
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
def test_settings_loads_phase2_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "vid-calm")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "vid-energetic")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "vid-deep")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "vid-warm")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "vid-myst")
    monkeypatch.setenv("PEXELS_API_KEY", "px-key")

    settings = Settings()

    assert settings.elevenlabs_api_key == "el-key"
    assert settings.elevenlabs_model == "eleven_multilingual_v2"
    assert settings.elevenlabs_voice_for_category("calm_narrator") == "vid-calm"
    assert settings.elevenlabs_voice_for_category("deep_documentary") == "vid-deep"
    assert settings.pexels_api_key == "px-key"
    assert settings.pexels_per_page == 10
    assert settings.whisper_model == "small"
    assert settings.whisper_device == "cpu"
    assert settings.whisper_compute_type == "int8"


def test_settings_voice_for_unknown_category_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "vid")
    monkeypatch.setenv("PEXELS_API_KEY", "px")

    settings = Settings()

    with pytest.raises(KeyError, match="unknown voice category"):
        settings.elevenlabs_voice_for_category("not_a_category")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_config.py::test_settings_loads_phase2_keys -v`
Expected: FAIL — attribute `elevenlabs_api_key` does not exist on Settings.

- [ ] **Step 4: Extend `Settings`**

Replace the contents of `src/yt_auto/config.py` with:

```python
"""Application settings loaded from environment / .env file."""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VoiceCategory = Literal[
    "calm_narrator",
    "energetic_explainer",
    "deep_documentary",
    "warm_storyteller",
    "mysterious_lowkey",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    gemini_api_key: str = Field(..., description="Google AI Studio / Gemini API key")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # Voice (ElevenLabs)
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key")
    elevenlabs_model: str = Field(default="eleven_multilingual_v2")
    elevenlabs_voice_calm_narrator: str = Field(default="")
    elevenlabs_voice_energetic_explainer: str = Field(default="")
    elevenlabs_voice_deep_documentary: str = Field(default="")
    elevenlabs_voice_warm_storyteller: str = Field(default="")
    elevenlabs_voice_mysterious_lowkey: str = Field(default="")

    # Footage (Pexels)
    pexels_api_key: str = Field(default="")
    pexels_per_page: int = Field(default=10, ge=1, le=80)

    # Captions (faster-whisper)
    whisper_model: str = Field(default="small")
    whisper_device: Literal["cpu", "cuda"] = Field(default="cpu")
    whisper_compute_type: str = Field(default="int8")

    # App
    data_dir: Path = Field(default=Path("./data"))
    outputs_dir: Path = Field(default=Path("./outputs"))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    def elevenlabs_voice_for_category(self, category: str) -> str:
        attr = f"elevenlabs_voice_{category}"
        if not hasattr(self, attr):
            raise KeyError(f"unknown voice category: {category}")
        value: str = getattr(self, attr)
        if not value:
            raise KeyError(f"no voice_id configured for category: {category}")
        return value


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_config.py -v`
Expected: 4 tests pass (the 2 existing + 2 new).

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/config.py tests/unit/test_config.py`
Expected: clean.

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/config.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add .env.example src/yt_auto/config.py tests/unit/test_config.py
git commit -m "Extend Settings with ElevenLabs/Pexels/Whisper keys + voice category lookup"
```

---

## Task 2 — Add Phase 2 dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new runtime deps**

In `pyproject.toml`, find the `dependencies` block under `[project]` and add the two new entries so it reads:

```toml
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.4",
    "structlog>=24.1",
    "jinja2>=3.1",
    "httpx>=0.27",
    "google-genai>=1.0",
    "python-ulid>=3.0",
    "elevenlabs>=1.5",
    "faster-whisper>=1.0",
]
```

- [ ] **Step 2: Add mypy override for the new untyped libs**

In `pyproject.toml`, find the existing `[[tool.mypy.overrides]]` block for `google.genai.*` and add two more overrides immediately after it:

```toml
[[tool.mypy.overrides]]
module = "elevenlabs.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "faster_whisper.*"
ignore_missing_imports = true
```

- [ ] **Step 3: Sync deps**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" sync --extra dev`
Expected: resolves cleanly, installs `elevenlabs` and `faster-whisper`. The faster-whisper install pulls a few hundred MB of CTranslate2 wheels — this is normal.

- [ ] **Step 4: Smoke-import the new libs**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run python -c "from elevenlabs.client import ElevenLabs; from faster_whisper import WhisperModel; print('ok')"`
Expected: prints `ok`. The first `WhisperModel` import does NOT yet download model files; that happens at instantiation time.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add elevenlabs and faster-whisper deps; mypy overrides"
```

---

## Task 3 — `ffmpeg/probe.py` (read media duration)

**Files:**
- Create: `src/yt_auto/ffmpeg/__init__.py`
- Create: `src/yt_auto/ffmpeg/probe.py`
- Create: `tests/unit/test_ffmpeg_probe.py`

- [ ] **Step 1: Write the failing test**

`src/yt_auto/ffmpeg/__init__.py`: empty file.

`tests/unit/test_ffmpeg_probe.py`:
```python
"""These tests shell out to real ffmpeg/ffprobe. They're fast (<2s) but require
ffmpeg on PATH. Skip with -k 'not ffmpeg' if you don't have it yet."""
import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.probe import probe_duration_s


def _make_silent_wav(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anullsrc=channel_layout=mono:sample_rate=22050",
            "-t", str(seconds), str(path),
        ],
        check=True, capture_output=True,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_probe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.ffmpeg'`.

- [ ] **Step 3: Implement `probe.py`**

`src/yt_auto/ffmpeg/probe.py`:
```python
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
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_probe.py -v`
Expected: both tests PASS. (Requires ffmpeg + ffprobe on PATH.)

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/ffmpeg/ tests/unit/test_ffmpeg_probe.py`
Expected: clean.

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/ffmpeg/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/ffmpeg/__init__.py src/yt_auto/ffmpeg/probe.py tests/unit/test_ffmpeg_probe.py
git commit -m "Add async ffprobe wrapper for reading media duration"
```

---

## Task 4 — `ffmpeg/prepare_clip.py` (trim/loop/scale one clip)

This helper turns one raw downloaded clip into a single normalized output of exact target duration and dimensions. The Media Agent calls this once per scene before the final concat.

**Files:**
- Create: `src/yt_auto/ffmpeg/prepare_clip.py`
- Create: `tests/unit/test_ffmpeg_prepare_clip.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ffmpeg_prepare_clip.py`:
```python
import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.ffmpeg.probe import probe_duration_s


def _make_test_video(path: Path, seconds: float, width: int, height: int) -> None:
    """Generate a solid-color test video at given duration + dimensions."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=red:size={width}x{height}:duration={seconds}:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True,
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
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(out)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(result.stdout)["streams"][0]
    assert streams["width"] == 1920
    assert streams["height"] == 1080
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_prepare_clip.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.ffmpeg.prepare_clip'`.

- [ ] **Step 3: Implement `prepare_clip.py`**

`src/yt_auto/ffmpeg/prepare_clip.py`:
```python
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
        "-i", str(src),
        "-t", f"{target_duration_s:.3f}",
        "-vf", vf,
        "-an",                                  # strip audio (we add narration later)
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "20",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_prepare_clip.py -v`
Expected: all 3 tests PASS. Each takes a few seconds because real ffmpeg is encoding.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/ffmpeg/prepare_clip.py tests/unit/test_ffmpeg_prepare_clip.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/ffmpeg/prepare_clip.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/ffmpeg/prepare_clip.py tests/unit/test_ffmpeg_prepare_clip.py
git commit -m "Add prepare_clip: trim/loop + scale-and-crop one source clip"
```

---

## Task 5 — `ffmpeg/concat.py` (concatenate prepared clips)

**Files:**
- Create: `src/yt_auto/ffmpeg/concat.py`
- Create: `tests/unit/test_ffmpeg_concat.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ffmpeg_concat.py`:
```python
import subprocess
from pathlib import Path

import pytest

from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.probe import probe_duration_s


def _make_test_video(path: Path, seconds: float, width: int = 1920, height: int = 1080) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"color=c=blue:size={width}x{height}:duration={seconds}:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True, capture_output=True,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_concat.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.ffmpeg.concat'`.

- [ ] **Step 3: Implement `concat.py`**

`src/yt_auto/ffmpeg/concat.py`:
```python
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
    manifest = dest.with_suffix(".concat.txt")
    manifest.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips),
        encoding="utf-8",
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(manifest),
            "-c", "copy",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_concat.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/ffmpeg/concat.py tests/unit/test_ffmpeg_concat.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/ffmpeg/`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/ffmpeg/concat.py tests/unit/test_ffmpeg_concat.py
git commit -m "Add concat_clips: stitch prepared clips via ffmpeg concat demuxer"
```

---

## Task 6 — `ffmpeg/render.py` (final mux with burned-in subtitles)

**Files:**
- Create: `src/yt_auto/ffmpeg/render.py`
- Create: `tests/unit/test_ffmpeg_render.py`
- Create: `tests/fixtures/sample.srt`

- [ ] **Step 1: Create the sample SRT fixture**

`tests/fixtures/sample.srt`:
```
1
00:00:00,000 --> 00:00:02,000
First line of captions.

2
00:00:02,000 --> 00:00:04,000
Second line of captions.
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_ffmpeg_render.py`:
```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.ffmpeg.render'`.

- [ ] **Step 4: Implement `render.py`**

`src/yt_auto/ffmpeg/render.py`:
```python
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
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-vf", vf,
        "-c:v", "libx264",
        "-b:v", video_bitrate,
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-shortest",                            # stop when narration ends
        "-movflags", "+faststart",              # YouTube/web playback
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_ffmpeg_render.py -v`
Expected: PASS. ~5 seconds for the real encode.

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/ffmpeg/render.py tests/unit/test_ffmpeg_render.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/ffmpeg/render.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/yt_auto/ffmpeg/render.py tests/unit/test_ffmpeg_render.py tests/fixtures/sample.srt
git commit -m "Add render_final: mux video+audio with burned-in libass subtitles"
```

---

## Task 7 — ElevenLabs client (`clients/elevenlabs.py`)

The official `elevenlabs` SDK is sync; we wrap each call in `asyncio.to_thread`. Tests use a fake constructor-injected SDK client.

**Files:**
- Create: `src/yt_auto/clients/elevenlabs.py`
- Create: `tests/unit/test_elevenlabs_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_elevenlabs_client.py`:
```python
from pathlib import Path
from typing import Any

import pytest

from yt_auto.clients.elevenlabs import ElevenLabsClient, ElevenLabsError


class _FakeTextToSpeech:
    """Stand-in for `elevenlabs.client.ElevenLabs().text_to_speech`."""

    def __init__(self, audio_bytes: bytes | None = None, raise_with: Exception | None = None) -> None:
        self._audio = audio_bytes
        self._raise = raise_with
        self.calls: list[dict[str, Any]] = []

    def convert(self, *, voice_id: str, text: str, model_id: str, output_format: str) -> Any:
        self.calls.append({
            "voice_id": voice_id, "text": text,
            "model_id": model_id, "output_format": output_format,
        })
        if self._raise:
            raise self._raise
        # SDK returns an iterator of bytes; we mimic that.
        assert self._audio is not None
        return iter([self._audio])


class _FakeElevenSDK:
    def __init__(self, text_to_speech: _FakeTextToSpeech) -> None:
        self.text_to_speech = text_to_speech


@pytest.mark.asyncio
async def test_synthesize_to_mp3_writes_file(tmp_path: Path) -> None:
    fake_tts = _FakeTextToSpeech(audio_bytes=b"\xff\xfb\x90\x00" * 100)
    sdk = _FakeElevenSDK(fake_tts)
    client = ElevenLabsClient(api_key="k", model="eleven_multilingual_v2", _sdk=sdk)

    dest = tmp_path / "voice.mp3"
    await client.synthesize_to_mp3(text="hello world", voice_id="vid-1", dest=dest)

    assert dest.exists()
    assert dest.read_bytes() == b"\xff\xfb\x90\x00" * 100
    assert fake_tts.calls[0]["voice_id"] == "vid-1"
    assert fake_tts.calls[0]["text"] == "hello world"
    assert fake_tts.calls[0]["model_id"] == "eleven_multilingual_v2"
    assert "mp3" in fake_tts.calls[0]["output_format"]


@pytest.mark.asyncio
async def test_synthesize_to_mp3_wraps_sdk_errors(tmp_path: Path) -> None:
    fake_tts = _FakeTextToSpeech(raise_with=RuntimeError("simulated 401"))
    client = ElevenLabsClient(api_key="k", model="m", _sdk=_FakeElevenSDK(fake_tts))

    with pytest.raises(ElevenLabsError, match="simulated 401"):
        await client.synthesize_to_mp3(text="hi", voice_id="v", dest=tmp_path / "voice.mp3")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_elevenlabs_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.clients.elevenlabs'`.

- [ ] **Step 3: Implement `elevenlabs.py`**

`src/yt_auto/clients/elevenlabs.py`:
```python
"""Async wrapper around the (sync) elevenlabs SDK for MP3 text-to-speech."""
import asyncio
from pathlib import Path
from typing import Any

from yt_auto.logging import get_logger

log = get_logger(__name__)


class ElevenLabsError(Exception):
    """Wraps any failure from the ElevenLabs SDK."""


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        model: str = "eleven_multilingual_v2",
        *,
        output_format: str = "mp3_44100_128",
        _sdk: Any = None,
    ) -> None:
        self._model = model
        self._output_format = output_format
        if _sdk is not None:
            self._sdk = _sdk
        else:
            from elevenlabs.client import ElevenLabs  # imported lazily for testability
            self._sdk = ElevenLabs(api_key=api_key)

    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None:
        """Synthesize `text` with `voice_id` and write the resulting MP3 to `dest`."""
        def _call() -> bytes:
            try:
                chunks = self._sdk.text_to_speech.convert(
                    voice_id=voice_id,
                    text=text,
                    model_id=self._model,
                    output_format=self._output_format,
                )
                return b"".join(chunks)
            except Exception as e:  # noqa: BLE001
                raise ElevenLabsError(str(e)) from e

        audio = await asyncio.to_thread(_call)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(audio)
        log.info("elevenlabs_synthesized", bytes=len(audio), dest=str(dest), voice_id=voice_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_elevenlabs_client.py -v`
Expected: both PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/clients/elevenlabs.py tests/unit/test_elevenlabs_client.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/clients/elevenlabs.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/clients/elevenlabs.py tests/unit/test_elevenlabs_client.py
git commit -m "Add async ElevenLabs client wrapping the sync SDK"
```

---

## Task 8 — Voice Agent (`agents/voice.py`)

**Files:**
- Create: `src/yt_auto/agents/voice.py`
- Create: `tests/unit/test_voice_agent.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_voice_agent.py`:
```python
import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.voice import VoiceAgent, VoiceConfigError
from yt_auto.pipeline.context import RunContext


class _FakeEleven:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mp3_bytes = b"\xff\xfb" + b"\x00" * 1000

    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None:
        self.calls.append({"text": text, "voice_id": voice_id, "dest": dest})
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.mp3_bytes)


async def _fake_probe(_path: Path) -> float:
    return 47.5  # pretend mp3 duration


def _make_ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="01HVOICE", topic="t", format="short",
        visibility="public", run_dir=tmp_path,
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={"voice_category": "calm_narrator"},
    )


def _write_script_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "narration": "Once upon a time there was a curious traveler.",
        "voice_category": "calm_narrator",
    }))


@pytest.mark.asyncio
async def test_voice_agent_synthesizes_and_records_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("yt_auto.agents.voice.probe_duration_s", _fake_probe)
    fake = _FakeEleven()
    agent = VoiceAgent(
        elevenlabs=fake,
        voice_id_for_category=lambda cat: "vid-calm" if cat == "calm_narrator" else "fail",
    )
    ctx = _make_ctx(tmp_path)
    _write_script_json(ctx.artifacts["script.json"])

    result = await agent.run(ctx)

    voice_path = result.artifacts["voice.mp3"]
    assert voice_path == tmp_path / "voice.mp3"
    assert voice_path.exists()
    assert fake.calls[0]["voice_id"] == "vid-calm"
    assert fake.calls[0]["text"] == "Once upon a time there was a curious traveler."
    assert result.metadata["voice_id"] == "vid-calm"
    assert result.metadata["actual_duration_s"] == 47.5


@pytest.mark.asyncio
async def test_voice_agent_uses_category_from_script_when_missing_in_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("yt_auto.agents.voice.probe_duration_s", _fake_probe)
    fake = _FakeEleven()
    agent = VoiceAgent(
        elevenlabs=fake,
        voice_id_for_category=lambda cat: "vid-deep" if cat == "deep_documentary" else "x",
    )
    ctx = RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={},  # no voice_category in metadata; must fall back to script.json
    )
    ctx.artifacts["script.json"].parent.mkdir(parents=True, exist_ok=True)
    ctx.artifacts["script.json"].write_text(json.dumps({
        "narration": "Words.", "voice_category": "deep_documentary",
    }))

    result = await agent.run(ctx)

    assert result.metadata["voice_id"] == "vid-deep"


@pytest.mark.asyncio
async def test_voice_agent_raises_for_unconfigured_voice(tmp_path: Path) -> None:
    def lookup(_cat: str) -> str:
        raise KeyError("no voice_id configured for category: calm_narrator")

    agent = VoiceAgent(elevenlabs=_FakeEleven(), voice_id_for_category=lookup)
    ctx = _make_ctx(tmp_path)
    _write_script_json(ctx.artifacts["script.json"])

    with pytest.raises(VoiceConfigError, match="no voice_id"):
        await agent.run(ctx)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_voice_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.agents.voice'`.

- [ ] **Step 3: Implement `voice.py`**

`src/yt_auto/agents/voice.py`:
```python
"""Voice Agent: turns script narration into voice.mp3 via ElevenLabs."""
import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)


class ElevenLabsLike(Protocol):
    async def synthesize_to_mp3(self, *, text: str, voice_id: str, dest: Path) -> None: ...


class VoiceConfigError(Exception):
    """The voice_category resolved by Script Agent has no voice_id in config."""


class VoiceAgent:
    name = "voice"

    def __init__(
        self,
        elevenlabs: ElevenLabsLike,
        voice_id_for_category: Callable[[str], str],
    ) -> None:
        self._eleven = elevenlabs
        self._lookup_voice = voice_id_for_category

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        narration: str = script["narration"]
        category: str = ctx.metadata.get("voice_category") or script["voice_category"]

        try:
            voice_id = self._lookup_voice(category)
        except KeyError as e:
            raise VoiceConfigError(str(e)) from e

        dest = ctx.run_dir / "voice.mp3"
        await self._eleven.synthesize_to_mp3(text=narration, voice_id=voice_id, dest=dest)
        actual_duration = await probe_duration_s(dest)
        log.info("voice_done", path=str(dest), duration_s=actual_duration)

        return StageResult(
            artifacts={"voice.mp3": dest},
            metadata={
                "voice_id": voice_id,
                "actual_duration_s": actual_duration,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_voice_agent.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/agents/voice.py tests/unit/test_voice_agent.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/agents/voice.py`
Expected: clean. (If ruff complains about the `_: Any = None` decoy, remove the `from typing import Any` and the decoy line — they may not be needed.)

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/agents/voice.py tests/unit/test_voice_agent.py
git commit -m "Add Voice Agent: ElevenLabs TTS + duration probe"
```

---

## Task 9 — Whisper client (`clients/whisper.py`)

**Files:**
- Create: `src/yt_auto/clients/whisper.py`
- Create: `tests/unit/test_whisper_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_whisper_client.py`:
```python
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from yt_auto.clients.whisper import Segment, WhisperClient


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str


class _FakeWhisperModel:
    """Stand-in for faster_whisper.WhisperModel."""

    def __init__(self, segments: list[_FakeSegment]) -> None:
        self._segments = segments

    def transcribe(
        self, _audio: str, **_kwargs: Any
    ) -> tuple[Iterator[_FakeSegment], dict[str, Any]]:
        return iter(self._segments), {"language": "en", "duration": 4.0}


@pytest.mark.asyncio
async def test_transcribe_returns_segments(tmp_path: Path) -> None:
    fake_model = _FakeWhisperModel([
        _FakeSegment(start=0.0, end=2.0, text="Hello world."),
        _FakeSegment(start=2.0, end=4.0, text="Goodbye."),
    ])
    client = WhisperClient(model_name="small", _model=fake_model)

    segments = await client.transcribe(tmp_path / "audio.mp3")

    assert len(segments) == 2
    assert segments[0] == Segment(start_s=0.0, end_s=2.0, text="Hello world.")
    assert segments[1] == Segment(start_s=2.0, end_s=4.0, text="Goodbye.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_whisper_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.clients.whisper'`.

- [ ] **Step 3: Implement `whisper.py`**

`src/yt_auto/clients/whisper.py`:
```python
"""Local faster-whisper wrapper. Sync internals, async surface via to_thread."""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_auto.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str


class WhisperClient:
    def __init__(
        self,
        *,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        _model: Any = None,
    ) -> None:
        if _model is not None:
            self._model = _model
        else:
            from faster_whisper import WhisperModel  # lazy import
            self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    async def transcribe(self, audio: Path) -> list[Segment]:
        def _call() -> list[Segment]:
            segments_iter, info = self._model.transcribe(str(audio))
            out = [
                Segment(start_s=float(s.start), end_s=float(s.end), text=s.text.strip())
                for s in segments_iter
            ]
            log.info(
                "whisper_done", segments=len(out),
                language=info.get("language") if isinstance(info, dict) else getattr(info, "language", None),
            )
            return out

        return await asyncio.to_thread(_call)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_whisper_client.py -v`
Expected: PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/clients/whisper.py tests/unit/test_whisper_client.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/clients/whisper.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/clients/whisper.py tests/unit/test_whisper_client.py
git commit -m "Add local faster-whisper async wrapper"
```

---

## Task 10 — Caption Agent (`agents/caption.py`)

**Files:**
- Create: `src/yt_auto/agents/caption.py`
- Create: `tests/unit/test_caption_agent.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_caption_agent.py`:
```python
from pathlib import Path

import pytest

from yt_auto.agents.caption import CaptionAgent
from yt_auto.clients.whisper import Segment
from yt_auto.pipeline.context import RunContext


class _FakeWhisper:
    def __init__(self, segments: list[Segment]) -> None:
        self._segments = segments
        self.transcribed: list[Path] = []

    async def transcribe(self, audio: Path) -> list[Segment]:
        self.transcribed.append(audio)
        return self._segments


def _ctx(tmp_path: Path) -> RunContext:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")
    return RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"voice.mp3": audio},
        metadata={},
    )


@pytest.mark.asyncio
async def test_caption_agent_writes_well_formed_srt(tmp_path: Path) -> None:
    fake = _FakeWhisper([
        Segment(start_s=0.0, end_s=2.0, text="Hello world."),
        Segment(start_s=2.5, end_s=4.25, text="And goodbye."),
    ])
    agent = CaptionAgent(whisper=fake)

    result = await agent.run(_ctx(tmp_path))

    srt_path = result.artifacts["captions.srt"]
    assert srt_path == tmp_path / "captions.srt"
    text = srt_path.read_text(encoding="utf-8")
    # SRT cue 1
    assert "1\n00:00:00,000 --> 00:00:02,000\nHello world." in text
    # SRT cue 2
    assert "2\n00:00:02,500 --> 00:00:04,250\nAnd goodbye." in text
    # Metadata
    assert result.metadata["word_count"] == 4  # "Hello world. And goodbye." → 4 tokens


@pytest.mark.asyncio
async def test_caption_agent_handles_empty_transcript(tmp_path: Path) -> None:
    agent = CaptionAgent(whisper=_FakeWhisper([]))

    with pytest.raises(ValueError, match="whisper returned zero segments"):
        await agent.run(_ctx(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_caption_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.agents.caption'`.

- [ ] **Step 3: Implement `caption.py`**

`src/yt_auto/agents/caption.py`:
```python
"""Caption Agent: runs Whisper on voice.mp3 and writes captions.srt."""
from pathlib import Path
from typing import Protocol

from yt_auto.clients.whisper import Segment
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)


class WhisperLike(Protocol):
    async def transcribe(self, audio: Path) -> list[Segment]: ...


def _fmt_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp `HH:MM:SS,mmm`."""
    if seconds < 0:
        seconds = 0
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _segments_to_srt(segments: list[Segment]) -> str:
    cues: list[str] = []
    for i, seg in enumerate(segments, start=1):
        cues.append(
            f"{i}\n{_fmt_srt_time(seg.start_s)} --> {_fmt_srt_time(seg.end_s)}\n{seg.text}\n"
        )
    return "\n".join(cues)


class CaptionAgent:
    name = "caption"

    def __init__(self, whisper: WhisperLike) -> None:
        self._whisper = whisper

    async def run(self, ctx: RunContext) -> StageResult:
        audio = ctx.artifacts["voice.mp3"]
        segments = await self._whisper.transcribe(audio)
        if not segments:
            raise ValueError("whisper returned zero segments")

        srt = _segments_to_srt(segments)
        dest = ctx.run_dir / "captions.srt"
        dest.write_text(srt, encoding="utf-8")

        word_count = sum(len(s.text.split()) for s in segments)
        log.info("caption_done", path=str(dest), segments=len(segments), words=word_count)

        return StageResult(
            artifacts={"captions.srt": dest},
            metadata={"word_count": word_count},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_caption_agent.py -v`
Expected: both PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/agents/caption.py tests/unit/test_caption_agent.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/agents/caption.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/agents/caption.py tests/unit/test_caption_agent.py
git commit -m "Add Caption Agent: whisper transcription → captions.srt"
```

---

## Task 11 — Pexels client (`clients/pexels.py`)

**Files:**
- Create: `src/yt_auto/clients/pexels.py`
- Create: `tests/fixtures/pexels_search_response.json`
- Create: `tests/unit/test_pexels_client.py`

- [ ] **Step 1: Create the Pexels search fixture**

`tests/fixtures/pexels_search_response.json`:
```json
{
  "page": 1,
  "per_page": 3,
  "total_results": 50,
  "videos": [
    {
      "id": 100,
      "width": 1920,
      "height": 1080,
      "duration": 12,
      "video_files": [
        {"id": 1, "quality": "hd", "width": 1920, "height": 1080, "link": "https://example.com/hd.mp4"},
        {"id": 2, "quality": "sd", "width": 640, "height": 360, "link": "https://example.com/sd.mp4"}
      ]
    },
    {
      "id": 101,
      "width": 1280,
      "height": 720,
      "duration": 5,
      "video_files": [
        {"id": 3, "quality": "hd", "width": 1280, "height": 720, "link": "https://example.com/hd2.mp4"}
      ]
    },
    {
      "id": 102,
      "width": 1920,
      "height": 1080,
      "duration": 20,
      "video_files": [
        {"id": 4, "quality": "hd", "width": 1920, "height": 1080, "link": "https://example.com/hd3.mp4"}
      ]
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_pexels_client.py`:
```python
import json
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.pexels import Clip, PexelsClient

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _stub_transport(handler: callable) -> httpx.MockTransport:  # type: ignore[valid-type]
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_videos_returns_clips_with_best_video_file() -> None:
    body = (FIXTURES / "pexels_search_response.json").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.pexels.com"
        assert "videos/search" in request.url.path
        assert request.url.params["query"] == "red sunset"
        assert request.url.params["per_page"] == "10"
        assert request.headers["Authorization"] == "test-key"
        return httpx.Response(200, content=body)

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="test-key", _http=http)
        clips = await client.search_videos(query="red sunset", per_page=10)

    assert len(clips) == 3
    assert clips[0] == Clip(id=100, duration_s=12, width=1920, height=1080,
                            url="https://example.com/hd.mp4")
    assert clips[1].url == "https://example.com/hd2.mp4"
    assert clips[2].url == "https://example.com/hd3.mp4"


@pytest.mark.asyncio
async def test_download_writes_file_to_dest(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(200, content=b"FAKE_MP4_BYTES")

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="k", _http=http)
        dest = tmp_path / "clip.mp4"
        await client.download(url="https://example.com/hd.mp4", dest=dest)

    assert dest.read_bytes() == b"FAKE_MP4_BYTES"


@pytest.mark.asyncio
async def test_search_videos_returns_empty_list_when_no_videos() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({
            "page": 1, "per_page": 10, "total_results": 0, "videos": [],
        }))

    transport = _stub_transport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PexelsClient(api_key="k", _http=http)
        clips = await client.search_videos(query="zzzzz", per_page=10)
    assert clips == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_pexels_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.clients.pexels'`.

- [ ] **Step 4: Implement `pexels.py`**

`src/yt_auto/clients/pexels.py`:
```python
"""Thin async client for Pexels video search + download."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from yt_auto.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.pexels.com"


@dataclass(frozen=True)
class Clip:
    id: int
    duration_s: int
    width: int
    height: int
    url: str


class PexelsClient:
    def __init__(self, api_key: str, *, _http: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        # Caller may pass a shared client; otherwise we make our own (caller responsible
        # for our lifecycle if they didn't pass one — typically we live inside a
        # short-lived agent call, so cleanup is implicit at process exit).
        self._http = _http or httpx.AsyncClient(timeout=30.0)

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        resp = await self._http.get(
            f"{_BASE_URL}/videos/search",
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            headers={"Authorization": self._api_key},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        clips: list[Clip] = []
        for v in data.get("videos", []):
            best = self._pick_best_video_file(v.get("video_files", []))
            if best is None:
                continue
            clips.append(Clip(
                id=int(v["id"]),
                duration_s=int(v["duration"]),
                width=int(best["width"]),
                height=int(best["height"]),
                url=str(best["link"]),
            ))
        log.info("pexels_search", query=query, clip_count=len(clips))
        return clips

    @staticmethod
    def _pick_best_video_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not files:
            return None
        # Prefer HD quality, then largest width.
        ranked = sorted(
            files,
            key=lambda f: (0 if f.get("quality") == "hd" else 1, -int(f.get("width", 0))),
        )
        return ranked[0]

    async def download(self, *, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._http.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        log.info("pexels_downloaded", url=url, dest=str(dest))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_pexels_client.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/clients/pexels.py tests/unit/test_pexels_client.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/clients/pexels.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/yt_auto/clients/pexels.py tests/fixtures/pexels_search_response.json tests/unit/test_pexels_client.py
git commit -m "Add Pexels async client: search_videos + stream download"
```

---

## Task 12 — Media Agent (`agents/media.py`)

For each scene: search Pexels with the scene's query, pick the best clip (shortest ≥ scene duration; if all shorter, longest looped), download, prepare via `prepare_clip`, then concat all prepared clips into `video_silent.mp4`. Scene durations are rescaled to match the actual voice.mp3 duration before clip selection.

**Files:**
- Create: `src/yt_auto/agents/media.py`
- Create: `tests/unit/test_media_agent.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_media_agent.py`:
```python
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.media import MediaAgent, MediaError, pick_best_clip, rescale_scenes
from yt_auto.clients.pexels import Clip
from yt_auto.pipeline.context import RunContext


def test_rescale_scenes_preserves_relative_proportions() -> None:
    scenes = [
        {"index": 0, "start_s": 0.0, "end_s": 10.0, "narration_excerpt": "a"},
        {"index": 1, "start_s": 10.0, "end_s": 30.0, "narration_excerpt": "b"},
        {"index": 2, "start_s": 30.0, "end_s": 50.0, "narration_excerpt": "c"},
    ]
    rescaled = rescale_scenes(scenes, target_total_duration_s=25.0)
    # Original durations 10/20/20 in a 50s total → 0.2/0.4/0.4 share → 5/10/10s
    assert rescaled[0]["end_s"] == pytest.approx(5.0)
    assert rescaled[1]["start_s"] == pytest.approx(5.0)
    assert rescaled[1]["end_s"] == pytest.approx(15.0)
    assert rescaled[2]["end_s"] == pytest.approx(25.0)


def test_pick_best_clip_prefers_shortest_at_or_above_target() -> None:
    clips = [
        Clip(id=1, duration_s=5, width=1920, height=1080, url="a"),
        Clip(id=2, duration_s=12, width=1920, height=1080, url="b"),
        Clip(id=3, duration_s=8, width=1920, height=1080, url="c"),
        Clip(id=4, duration_s=20, width=1920, height=1080, url="d"),
    ]
    picked = pick_best_clip(clips, target_duration_s=7.0)
    assert picked.id == 3  # shortest that is >= 7s


def test_pick_best_clip_falls_back_to_longest_when_all_shorter() -> None:
    clips = [
        Clip(id=1, duration_s=2, width=1920, height=1080, url="a"),
        Clip(id=2, duration_s=4, width=1920, height=1080, url="b"),
        Clip(id=3, duration_s=3, width=1920, height=1080, url="c"),
    ]
    picked = pick_best_clip(clips, target_duration_s=10.0)
    assert picked.id == 2  # longest available; agent will loop it


def test_pick_best_clip_empty_list_raises() -> None:
    with pytest.raises(MediaError, match="no clips"):
        pick_best_clip([], target_duration_s=5.0)


class _FakePexels:
    def __init__(self, results_by_query: dict[str, list[Clip]]) -> None:
        self._results = results_by_query
        self.searches: list[tuple[str, int]] = []
        self.downloads: list[tuple[str, Path]] = []

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        self.searches.append((query, per_page))
        return self._results.get(query, [])

    async def download(self, *, url: str, dest: Path) -> None:
        self.downloads.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE")


def _make_async_no_op(record: list[Any]) -> Callable[..., Awaitable[None]]:
    async def _fn(**kwargs: Any) -> None:
        record.append(kwargs)
    return _fn


def _make_ctx(tmp_path: Path) -> RunContext:
    script = tmp_path / "script.json"
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"fake")
    script.write_text(json.dumps({
        "format": "short",
        "scenes": [
            {"index": 0, "start_s": 0.0, "end_s": 5.0, "narration_excerpt": "a",
             "visual_prompt": "x", "pexels_query": "sunset beach"},
            {"index": 1, "start_s": 5.0, "end_s": 10.0, "narration_excerpt": "b",
             "visual_prompt": "y", "pexels_query": "mountain trail"},
        ],
    }))
    return RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": script, "voice.mp3": voice},
        metadata={"actual_duration_s": 8.0},
    )


@pytest.mark.asyncio
async def test_media_agent_searches_downloads_prepares_concats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pexels = _FakePexels({
        "sunset beach": [Clip(id=1, duration_s=10, width=1920, height=1080, url="u1")],
        "mountain trail": [Clip(id=2, duration_s=10, width=1920, height=1080, url="u2")],
    })
    prepare_calls: list[Any] = []
    concat_calls: list[Any] = []
    monkeypatch.setattr("yt_auto.agents.media.prepare_clip", _make_async_no_op(prepare_calls))

    async def fake_concat(**kwargs: Any) -> None:
        concat_calls.append(kwargs)
        kwargs["dest"].write_bytes(b"silent_video")
    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(pexels=fake_pexels, per_page=10)
    result = await agent.run(_make_ctx(tmp_path))

    # Both queries were searched
    assert {s[0] for s in fake_pexels.searches} == {"sunset beach", "mountain trail"}
    # Both clips were downloaded
    assert len(fake_pexels.downloads) == 2
    # prepare_clip called twice (one per scene) with rescaled target durations.
    # actual_duration_s=8 vs script total=10 → scale 0.8: 5→4s, 5→4s
    assert len(prepare_calls) == 2
    assert prepare_calls[0]["target_duration_s"] == pytest.approx(4.0)
    assert prepare_calls[1]["target_duration_s"] == pytest.approx(4.0)
    # concat called with two prepared clips
    assert len(concat_calls) == 1
    assert len(concat_calls[0]["clips"]) == 2
    assert result.artifacts["video_silent.mp4"] == tmp_path / "video_silent.mp4"
    assert result.metadata["clip_count"] == 2


@pytest.mark.asyncio
async def test_media_agent_fails_when_scene_has_no_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pexels = _FakePexels({"sunset beach": []})  # zero results
    monkeypatch.setattr("yt_auto.agents.media.prepare_clip", _make_async_no_op([]))
    monkeypatch.setattr("yt_auto.agents.media.concat_clips", _make_async_no_op([]))

    agent = MediaAgent(pexels=fake_pexels, per_page=10)
    with pytest.raises(MediaError, match="no clips"):
        await agent.run(_make_ctx(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_media_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.agents.media'`.

- [ ] **Step 3: Implement `media.py`**

`src/yt_auto/agents/media.py`:
```python
"""Media Agent: search Pexels per scene, download, normalize, concat to silent video."""
import json
from pathlib import Path
from typing import Any, Literal, Protocol

from yt_auto.clients.pexels import Clip
from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

# Render dimensions for each format.
_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30


class MediaError(Exception):
    """Could not produce video_silent.mp4."""


class PexelsLike(Protocol):
    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]: ...
    async def download(self, *, url: str, dest: Path) -> None: ...


def rescale_scenes(
    scenes: list[dict[str, Any]], *, target_total_duration_s: float
) -> list[dict[str, Any]]:
    if not scenes:
        raise MediaError("rescale_scenes needs at least one scene")
    original_total = scenes[-1]["end_s"] - scenes[0]["start_s"]
    if original_total <= 0:
        raise MediaError("scenes have zero total duration")
    factor = target_total_duration_s / original_total
    rescaled: list[dict[str, Any]] = []
    cursor = 0.0
    for sc in scenes:
        duration = (sc["end_s"] - sc["start_s"]) * factor
        rescaled.append({**sc, "start_s": cursor, "end_s": cursor + duration})
        cursor += duration
    # Snap last end exactly to target.
    rescaled[-1]["end_s"] = target_total_duration_s
    return rescaled


def pick_best_clip(clips: list[Clip], *, target_duration_s: float) -> Clip:
    if not clips:
        raise MediaError("no clips returned from Pexels for this scene")
    qualifying = [c for c in clips if c.duration_s >= target_duration_s]
    if qualifying:
        return min(qualifying, key=lambda c: c.duration_s)
    return max(clips, key=lambda c: c.duration_s)


class MediaAgent:
    name = "media"

    def __init__(self, pexels: PexelsLike, *, per_page: int = 10) -> None:
        self._pexels = pexels
        self._per_page = per_page

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        actual_voice_duration: float = ctx.metadata["actual_duration_s"]
        scenes = rescale_scenes(script["scenes"], target_total_duration_s=actual_voice_duration)
        fmt: Literal["long", "short"] = script["format"]
        width, height = _DIMS_BY_FORMAT[fmt]

        footage_dir = ctx.run_dir / "footage"
        footage_dir.mkdir(parents=True, exist_ok=True)
        prepared_paths: list[Path] = []

        for scene in scenes:
            query: str = scene["pexels_query"]
            target = float(scene["end_s"] - scene["start_s"])
            clips = await self._pexels.search_videos(query=query, per_page=self._per_page)
            picked = pick_best_clip(clips, target_duration_s=target)

            raw_path = footage_dir / f"scene_{scene['index']:03d}_raw.mp4"
            prepared_path = footage_dir / f"scene_{scene['index']:03d}.mp4"
            await self._pexels.download(url=picked.url, dest=raw_path)
            await prepare_clip(
                src=raw_path, dest=prepared_path,
                target_duration_s=target,
                width=width, height=height, fps=_FPS,
            )
            prepared_paths.append(prepared_path)

        dest = ctx.run_dir / "video_silent.mp4"
        await concat_clips(clips=prepared_paths, dest=dest)
        log.info("media_done", path=str(dest), clips=len(prepared_paths))

        return StageResult(
            artifacts={"video_silent.mp4": dest},
            metadata={"clip_count": len(prepared_paths)},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_media_agent.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/agents/media.py tests/unit/test_media_agent.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/agents/media.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/agents/media.py tests/unit/test_media_agent.py
git commit -m "Add Media Agent: Pexels search + clip selection + prepare + concat"
```

---

## Task 13 — Render Agent (`agents/render.py`)

**Files:**
- Create: `src/yt_auto/agents/render.py`
- Create: `tests/unit/test_render_agent.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_render_agent.py`:
```python
import json
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.render import RenderAgent
from yt_auto.pipeline.context import RunContext


async def _fake_probe(path: Path) -> float:
    return 47.5 if path.name == "final.mp4" else 0.0


def _make_ctx(tmp_path: Path) -> RunContext:
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"format": "long"}))
    video = tmp_path / "video_silent.mp4"
    audio = tmp_path / "voice.mp3"
    srt = tmp_path / "captions.srt"
    for p in (video, audio, srt):
        p.write_bytes(b"fake")
    return RunContext(
        run_id="r", topic="t", format="long", visibility="public",
        run_dir=tmp_path,
        artifacts={
            "script.json": script,
            "video_silent.mp4": video,
            "voice.mp3": audio,
            "captions.srt": srt,
        },
        metadata={},
    )


@pytest.mark.asyncio
async def test_render_agent_invokes_render_final_with_correct_dims_for_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_render_final(**kwargs: Any) -> None:
        captured.update(kwargs)
        kwargs["dest"].write_bytes(b"final_mp4")

    monkeypatch.setattr("yt_auto.agents.render.render_final", fake_render_final)
    monkeypatch.setattr("yt_auto.agents.render.probe_duration_s", _fake_probe)

    agent = RenderAgent()
    result = await agent.run(_make_ctx(tmp_path))

    assert captured["width"] == 1920
    assert captured["height"] == 1080
    assert captured["dest"] == tmp_path / "final.mp4"
    assert result.artifacts["final.mp4"].exists()
    assert result.metadata["final_duration_s"] == 47.5
    assert result.metadata["file_size_mb"] == pytest.approx(
        len(b"final_mp4") / (1024 * 1024), rel=1e-3
    )


@pytest.mark.asyncio
async def test_render_agent_uses_short_dims_when_format_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_render_final(**kwargs: Any) -> None:
        captured.update(kwargs)
        kwargs["dest"].write_bytes(b"final_mp4_short")

    monkeypatch.setattr("yt_auto.agents.render.render_final", fake_render_final)
    monkeypatch.setattr("yt_auto.agents.render.probe_duration_s", _fake_probe)

    ctx = _make_ctx(tmp_path)
    # Override script.json to short
    ctx.artifacts["script.json"].write_text(json.dumps({"format": "short"}))
    ctx = RunContext(
        run_id=ctx.run_id, topic=ctx.topic, format="short",
        visibility=ctx.visibility, run_dir=ctx.run_dir,
        artifacts=ctx.artifacts, metadata=ctx.metadata,
    )

    agent = RenderAgent()
    await agent.run(ctx)

    assert captured["width"] == 1080
    assert captured["height"] == 1920
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_render_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.agents.render'`.

- [ ] **Step 3: Implement `render.py`**

`src/yt_auto/agents/render.py`:
```python
"""Render Agent: mux silent video + narration + burned-in captions → final.mp4."""
from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.ffmpeg.render import render_final
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30
_VIDEO_BITRATE = "8M"
_AUDIO_BITRATE = "192k"


class RenderAgent:
    name = "render"

    async def run(self, ctx: RunContext) -> StageResult:
        width, height = _DIMS_BY_FORMAT[ctx.format]
        dest = ctx.run_dir / "final.mp4"

        await render_final(
            video=ctx.artifacts["video_silent.mp4"],
            audio=ctx.artifacts["voice.mp3"],
            subtitles=ctx.artifacts["captions.srt"],
            dest=dest,
            width=width, height=height,
            video_bitrate=_VIDEO_BITRATE, audio_bitrate=_AUDIO_BITRATE,
            fps=_FPS,
        )

        duration = await probe_duration_s(dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        log.info("render_done", path=str(dest), duration_s=duration, size_mb=size_mb)

        return StageResult(
            artifacts={"final.mp4": dest},
            metadata={
                "final_duration_s": duration,
                "file_size_mb": size_mb,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_render_agent.py -v`
Expected: both PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/agents/render.py tests/unit/test_render_agent.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/agents/render.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/agents/render.py tests/unit/test_render_agent.py
git commit -m "Add Render Agent: final mux via ffmpeg render_final"
```

---

## Task 14 — Add run-context rehydration helper

The per-agent CLI subcommands need to reconstruct a `RunContext` from `outputs/<run-id>/`. Adding a small loader on `RunContext` is the cleanest place.

**Files:**
- Modify: `src/yt_auto/pipeline/context.py`
- Modify: `tests/unit/test_pipeline_context.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pipeline_context.py`:

```python
import json

from yt_auto.pipeline.context import load_run_context_from_disk


def test_load_run_context_from_disk_rehydrates_minimal_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HZZ"
    run_dir.mkdir()
    (run_dir / "script.json").write_text(json.dumps({
        "topic": "the history of espresso",
        "format": "short",
        "voice_category": "calm_narrator",
    }))

    ctx = load_run_context_from_disk(run_dir, visibility="public")

    assert ctx.run_id == "01HZZ"
    assert ctx.topic == "the history of espresso"
    assert ctx.format == "short"
    assert ctx.run_dir == run_dir
    assert ctx.artifacts == {"script.json": run_dir / "script.json"}
    assert ctx.metadata["voice_category"] == "calm_narrator"


def test_load_run_context_from_disk_includes_existing_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HXX"
    run_dir.mkdir()
    (run_dir / "script.json").write_text(json.dumps({
        "topic": "t", "format": "long", "voice_category": "deep_documentary",
    }))
    (run_dir / "voice.mp3").write_bytes(b"x")
    (run_dir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

    ctx = load_run_context_from_disk(run_dir, visibility="private")

    assert ctx.visibility == "private"
    assert set(ctx.artifacts) == {"script.json", "voice.mp3", "captions.srt"}


def test_load_run_context_from_disk_missing_script_raises(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HQQ"
    run_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="script.json"):
        load_run_context_from_disk(run_dir, visibility="public")
```

(Add `import pytest` to the imports at the top of the file if not already there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_pipeline_context.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_run_context_from_disk'`.

- [ ] **Step 3: Implement the loader**

First, add `import json` to the top of `src/yt_auto/pipeline/context.py` (right after the existing `from dataclasses import ...` line — keep `from pathlib import Path` and `from typing import ...` in their current positions; the import block follows standard ordering).

Then **append** the constant and function to the end of the file (after the existing late import of `StageResult`):

```python
# Logical artifact names that may exist in a run directory at various stages.
_KNOWN_ARTIFACT_FILES = (
    "script.json",
    "voice.mp3",
    "captions.srt",
    "video_silent.mp4",
    "final.mp4",
    "upload.json",
)


def load_run_context_from_disk(run_dir: Path, *, visibility: Visibility) -> RunContext:
    """Rehydrate a RunContext from `outputs/<run_id>/` for resume / per-agent runs.

    Reads script.json for topic/format/voice_category. Discovers existing artifacts
    by filename so later stages can find what earlier stages produced.
    """
    script_path = run_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"script.json not found in {run_dir}")
    script = json.loads(script_path.read_text())

    artifacts: dict[str, Path] = {}
    for name in _KNOWN_ARTIFACT_FILES:
        p = run_dir / name
        if p.exists():
            artifacts[name] = p

    metadata: dict[str, Any] = {}
    if "voice_category" in script:
        metadata["voice_category"] = script["voice_category"]

    return RunContext(
        run_id=run_dir.name,
        topic=script["topic"],
        format=script["format"],
        visibility=visibility,
        run_dir=run_dir,
        artifacts=artifacts,
        metadata=metadata,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_pipeline_context.py -v`
Expected: all PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/pipeline/context.py tests/unit/test_pipeline_context.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/pipeline/context.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/pipeline/context.py tests/unit/test_pipeline_context.py
git commit -m "Add load_run_context_from_disk for per-agent CLI rehydration"
```

---

## Task 15 — Extend CLI with `voice`, `caption`, `media`, `render`, `pipeline-local` subcommands

This is one task because the subcommands all share parser-building patterns and helper construction, and breaking them apart would mean trivial diffs and constant repackaging.

**Files:**
- Modify: `src/yt_auto/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
class StubVoice:
    name = "voice"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult
        self.ran_with = ctx
        dest = ctx.run_dir / "voice.mp3"
        dest.write_bytes(b"x")
        return StageResult(artifacts={"voice.mp3": dest}, metadata={"actual_duration_s": 1.0})


def _seed_run_dir(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(json.dumps({
        "topic": "t", "format": "short", "voice_category": "calm_narrator",
    }))


def test_cli_voice_subcommand_loads_run_and_invokes_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "01HZZ"
    _seed_run_dir(run_dir)

    stub = StubVoice()

    def fake_build_voice(_settings: Any) -> Any:
        return stub

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "y")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setattr("yt_auto.cli.build_voice_agent", fake_build_voice)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "voice", "01HZZ"])

    main()

    out = capsys.readouterr().out
    assert "voice.mp3" in out
    assert stub.ran_with.run_id == "01HZZ"
    assert stub.ran_with.topic == "t"


def test_cli_caption_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "caption", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_media_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "media", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_render_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "render", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_pipeline_local_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "pipeline-local", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_cli.py -v`
Expected: 5 new tests FAIL with `AttributeError: module 'yt_auto.cli' has no attribute 'build_voice_agent'` and missing subcommand errors.

- [ ] **Step 3: Rewrite `src/yt_auto/cli.py`**

Replace the entire contents of `src/yt_auto/cli.py` with:

```python
"""Command-line entrypoint.

Subcommands:
- script <topic>            run Script Agent for a fresh run
- voice <run-id>            run Voice Agent on an existing run
- caption <run-id>          run Caption Agent on an existing run
- media <run-id>            run Media Agent on an existing run
- render <run-id>           run Render Agent on an existing run
- pipeline-local <topic>    chain script→voice→media→caption→render for a fresh run
"""
import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from ulid import ULID

from yt_auto.agents.caption import CaptionAgent
from yt_auto.agents.media import MediaAgent
from yt_auto.agents.render import RenderAgent
from yt_auto.agents.script import ScriptAgent
from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.clients.gemini import GeminiClient
from yt_auto.clients.pexels import PexelsClient
from yt_auto.clients.whisper import WhisperClient
from yt_auto.config import Settings, get_settings
from yt_auto.logging import configure_logging, get_logger
from yt_auto.pipeline.base import Agent
from yt_auto.pipeline.context import RunContext, load_run_context_from_disk


def build_script_agent(settings: Settings) -> ScriptAgent:
    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return ScriptAgent(gemini=gemini)


def build_voice_agent(settings: Settings) -> VoiceAgent:
    eleven = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    return VoiceAgent(
        elevenlabs=eleven,
        voice_id_for_category=settings.elevenlabs_voice_for_category,
    )


def build_caption_agent(settings: Settings) -> CaptionAgent:
    whisper = WhisperClient(
        model_name=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    return CaptionAgent(whisper=whisper)


def build_media_agent(settings: Settings) -> MediaAgent:
    pexels = PexelsClient(api_key=settings.pexels_api_key)
    return MediaAgent(pexels=pexels, per_page=settings.pexels_per_page)


def build_render_agent(_settings: Settings) -> RenderAgent:
    return RenderAgent()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt_auto", description="YouTube automation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    # script
    p_script = sub.add_parser("script", help="Run Script Agent for a fresh run")
    p_script.add_argument("topic")
    p_script.add_argument("--format", choices=["long", "short"], default="long")
    p_script.add_argument("--seed", type=int, default=None)
    p_script.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")

    # voice / caption / media / render — all share the same shape
    for name in ("voice", "caption", "media", "render"):
        p = sub.add_parser(name, help=f"Run {name.capitalize()} Agent on an existing run")
        p.add_argument("run_id", help="ULID of an existing run under outputs/")
        p.add_argument(
            "--visibility", choices=["public", "unlisted", "private"], default="public",
            help="Sets RunContext.visibility (not used until upload phase)",
        )

    # pipeline-local: fresh run, run all 5 in order, no upload
    p_pipe = sub.add_parser(
        "pipeline-local",
        help="Run script→voice→media→caption→render end-to-end locally",
    )
    p_pipe.add_argument("topic")
    p_pipe.add_argument("--format", choices=["long", "short"], default="long")
    p_pipe.add_argument("--seed", type=int, default=None)
    p_pipe.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")

    return parser


def _new_run_context(settings: Settings, args: argparse.Namespace) -> RunContext:
    run_id = str(ULID())
    return RunContext(
        run_id=run_id,
        topic=args.topic,
        format=args.format,
        visibility=args.visibility,
        run_dir=settings.outputs_dir / run_id,
        artifacts={},
        metadata={"seed": args.seed} if args.seed is not None else {},
    )


async def _run_single_agent_on_existing(
    settings: Settings,
    args: argparse.Namespace,
    builder: Callable[[Settings], Agent],
) -> Path:
    run_dir = settings.outputs_dir / args.run_id
    ctx = load_run_context_from_disk(run_dir, visibility=args.visibility)
    agent = builder(settings)
    result = await agent.run(ctx)
    return next(iter(result.artifacts.values()))


async def _run_script(settings: Settings, args: argparse.Namespace) -> Path:
    ctx = _new_run_context(settings, args)
    agent = build_script_agent(settings)
    result = await agent.run(ctx)
    return result.artifacts["script.json"]


async def _run_pipeline_local(settings: Settings, args: argparse.Namespace) -> Path:
    ctx = _new_run_context(settings, args)

    script_agent = build_script_agent(settings)
    ctx = ctx.merge(await script_agent.run(ctx))

    voice_agent = build_voice_agent(settings)
    ctx = ctx.merge(await voice_agent.run(ctx))

    media_agent = build_media_agent(settings)
    ctx = ctx.merge(await media_agent.run(ctx))

    caption_agent = build_caption_agent(settings)
    ctx = ctx.merge(await caption_agent.run(ctx))

    render_agent = build_render_agent(settings)
    result = await render_agent.run(ctx)
    return result.artifacts["final.mp4"]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("cli")

    if args.command == "script":
        out_path = asyncio.run(_run_script(settings, args))
    elif args.command == "voice":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_voice_agent))
    elif args.command == "caption":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_caption_agent))
    elif args.command == "media":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_media_agent))
    elif args.command == "render":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_render_agent))
    elif args.command == "pipeline-local":
        out_path = asyncio.run(_run_pipeline_local(settings, args))
    else:
        parser.error(f"unknown command: {args.command}")
        sys.exit(2)

    log.info("done", command=args.command, path=str(out_path))
    print(f"Wrote {out_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_cli.py -v`
Expected: all CLI tests PASS (the original 4 + 5 new = 9 total).

- [ ] **Step 5: Smoke-check all new subcommands respond to `--help`**

Run each in turn:
```
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto voice --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto caption --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto media --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto render --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto pipeline-local --help
```
Expected: each prints usage and exits 0.

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/cli.py tests/unit/test_cli.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/cli.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/yt_auto/cli.py tests/unit/test_cli.py
git commit -m "Extend CLI: voice/caption/media/render/pipeline-local subcommands"
```

---

## Task 16 — Opt-in integration tests for Phase 2

These test the real APIs end-to-end. Skip silently when keys are absent.

**Files:**
- Create: `tests/integration/test_voice_agent_live.py`
- Create: `tests/integration/test_pexels_client_live.py`
- Create: `tests/integration/test_pipeline_local_live.py`

- [ ] **Step 1: Create the Voice integration test**

`tests/integration/test_voice_agent_live.py`:
```python
"""Live test against ElevenLabs. Run with: pytest -m integration."""
import json
import os
from pathlib import Path

import pytest

from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.config import get_settings
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("ELEVENLABS_API_KEY"),
    reason="ELEVENLABS_API_KEY not set",
)
async def test_voice_agent_against_real_elevenlabs(tmp_path: Path) -> None:
    settings = get_settings()
    # Sanity: at least one voice id must be configured.
    try:
        voice_id = settings.elevenlabs_voice_for_category("calm_narrator")
    except KeyError:
        pytest.skip("ELEVENLABS_VOICE_CALM_NARRATOR not set in .env")

    client = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    agent = VoiceAgent(elevenlabs=client, voice_id_for_category=settings.elevenlabs_voice_for_category)

    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps({
        "narration": "This is a brief test of the voice agent. One short sentence.",
        "voice_category": "calm_narrator",
    }))
    ctx = RunContext(
        run_id="voice-smoke", topic="t", format="short", visibility="private",
        run_dir=tmp_path,
        artifacts={"script.json": script_path},
        metadata={"voice_category": "calm_narrator"},
    )

    result = await agent.run(ctx)

    assert result.artifacts["voice.mp3"].stat().st_size > 1000  # at least 1 KB of audio
    assert result.metadata["actual_duration_s"] > 0
    assert result.metadata["voice_id"] == voice_id
```

- [ ] **Step 2: Create the Pexels integration test**

`tests/integration/test_pexels_client_live.py`:
```python
"""Live test against Pexels. Run with: pytest -m integration."""
import os
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.pexels import PexelsClient

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("PEXELS_API_KEY"),
    reason="PEXELS_API_KEY not set",
)
async def test_pexels_search_returns_clips(tmp_path: Path) -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        client = PexelsClient(api_key=os.environ["PEXELS_API_KEY"], _http=http)
        clips = await client.search_videos(query="sunset beach", per_page=5)
        assert len(clips) > 0
        assert all(c.duration_s > 0 for c in clips)

        # Download the first one to verify download flow
        dest = tmp_path / "clip.mp4"
        await client.download(url=clips[0].url, dest=dest)
        assert dest.stat().st_size > 10_000  # at least 10 KB
```

- [ ] **Step 3: Create the full pipeline-local integration test**

`tests/integration/test_pipeline_local_live.py`:
```python
"""Full end-to-end against ALL real APIs (Gemini + ElevenLabs + Pexels) + ffmpeg + Whisper.

Heavy: takes 60-180 seconds and costs ~$0.10. Run with: pytest -m integration."""
import os
from pathlib import Path

import pytest

from yt_auto.agents.caption import CaptionAgent
from yt_auto.agents.media import MediaAgent
from yt_auto.agents.render import RenderAgent
from yt_auto.agents.script import ScriptAgent
from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.clients.gemini import GeminiClient
from yt_auto.clients.pexels import PexelsClient
from yt_auto.clients.whisper import WhisperClient
from yt_auto.config import get_settings
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


def _all_keys_present() -> bool:
    return bool(
        os.getenv("GEMINI_API_KEY")
        and os.getenv("ELEVENLABS_API_KEY")
        and os.getenv("PEXELS_API_KEY")
    )


@pytest.mark.skipif(not _all_keys_present(),
                    reason="Gemini / ElevenLabs / Pexels keys required")
async def test_pipeline_local_end_to_end(tmp_path: Path) -> None:
    settings = get_settings()

    ctx = RunContext(
        run_id="pipeline-smoke", topic="the history of espresso",
        format="short", visibility="private",
        run_dir=tmp_path, artifacts={}, metadata={"seed": 11},
    )

    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    ctx = ctx.merge(await ScriptAgent(gemini=gemini).run(ctx))

    eleven = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    voice_agent = VoiceAgent(elevenlabs=eleven,
                             voice_id_for_category=settings.elevenlabs_voice_for_category)
    ctx = ctx.merge(await voice_agent.run(ctx))

    pexels = PexelsClient(api_key=settings.pexels_api_key)
    ctx = ctx.merge(await MediaAgent(pexels=pexels, per_page=settings.pexels_per_page).run(ctx))

    whisper = WhisperClient(model_name=settings.whisper_model,
                            device=settings.whisper_device,
                            compute_type=settings.whisper_compute_type)
    ctx = ctx.merge(await CaptionAgent(whisper=whisper).run(ctx))

    ctx = ctx.merge(await RenderAgent().run(ctx))

    final = ctx.artifacts["final.mp4"]
    assert final.exists()
    assert final.stat().st_size > 1_000_000  # at least 1 MB
    assert ctx.metadata["final_duration_s"] > 10  # short format ≈ 50s
```

- [ ] **Step 4: Confirm tests are gated by markers + key presence**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -m integration -v`
Expected (no keys): all three integration tests collected and skipped with their respective "not set" reasons.

- [ ] **Step 5: Run ruff**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check tests/integration/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_voice_agent_live.py tests/integration/test_pexels_client_live.py tests/integration/test_pipeline_local_live.py
git commit -m "Add opt-in integration tests for Voice/Pexels and full pipeline-local"
```

---

## Task 17 — Final Phase 2 verification

- [ ] **Step 1: Run the full unit test suite**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v`
Expected: all unit tests PASS, integration tests deselected.

- [ ] **Step 2: Run ruff check**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Run ruff format**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format src tests`
Expected: any files newly reformatted should be staged + committed below.

Then run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format --check src tests`
Expected: all files already formatted.

- [ ] **Step 4: Run mypy strict**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto`
Expected: `Success: no issues found`.

- [ ] **Step 5: Run pytest with coverage**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest --cov=yt_auto --cov-report=term-missing`
Expected: coverage on every agent and every client module ≥ 90%.

- [ ] **Step 6: If Step 3 reformatted anything, commit**

```bash
git add -A
git commit -m "Apply ruff format across Phase 2 modules"
```

(If nothing changed, skip this step.)

- [ ] **Step 7: Tag the Phase 2 milestone**

```bash
git tag -a phase-2-content-agents -m "Phase 2 milestone: Voice + Caption + Media + Render agents"
```

(Numbered per-task tags `0.0.12` through `0.0.x` are handled by the controller in the same way Phase 1 was.)

---

## Notes for the engineer

- **TDD discipline:** every task's first impl step is preceded by a failing-test step. Don't skip the "watch it fail" — that's how you confirm the test is wired.
- **ffmpeg tests run real ffmpeg.** They're not mocks. If `ffmpeg`/`ffprobe` isn't on PATH, those tests will fail with `FileNotFoundError`. Install ffmpeg first.
- **Whisper first run downloads its model.** Tests use a fake `_model`, so unit tests don't download anything. The live integration test will trigger a ~500 MB download on first run.
- **ElevenLabs SDK is sync.** We wrap each call in `asyncio.to_thread`. Don't try to use the alpha async surface — it's not stable.
- **Pexels orientation:** the client requests `orientation=landscape` by default. Shorts (vertical) would benefit from `orientation=portrait`; that's a Phase 2.5 follow-up the plan doesn't address yet. For now, landscape footage scaled-and-cropped to 1080x1920 is acceptable.
- **No music track.** Spec says Phase 1+2 are narration-only. Don't add a music mix.
- **No Upload Agent.** That's Phase 3.

## Out of scope for Phase 2

- Upload Agent (Phase 3)
- FastAPI + Web UI (Phase 5)
- SQLite job store + resumable executor (Phase 4)
- Pexels orientation per format
- Background music
- Thumbnail generation
- Multiple language support
