# Local SDXL B-Roll Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic Pexels stock footage with locally generated SDXL images animated via ffmpeg Ken Burns. Pexels stays as a per-scene fallback so a broken ComfyUI never kills a run.

**Architecture:** Strategy pattern — `MediaAgent` delegates per-scene clip production to a `SceneSource`. `LocalDiffusionSource` calls a local ComfyUI HTTP server for SDXL image gen, then runs an ffmpeg `zoompan` pass to produce the clip. `PexelsSource` is the current Pexels flow extracted behind the same interface. On per-scene failure, `MediaAgent` falls back from local to Pexels.

**Tech Stack:** Python 3.12, async/await, `httpx.AsyncClient`, ffmpeg subprocess, pydantic-settings, ComfyUI (external process), SDXL base 1.0.

**Spec:** [2026-06-19-local-sdxl-broll-design.md](../specs/2026-06-19-local-sdxl-broll-design.md)

---

## File map

**Create:**
- `src/yt_auto/clients/comfyui.py` — `ComfyUIClient`, `ComfyUIError`
- `src/yt_auto/clients/workflows/__init__.py` — empty marker so workflows ships with the package
- `src/yt_auto/clients/workflows/sdxl_txt2img.json` — SDXL text2img workflow template
- `src/yt_auto/ffmpeg/ken_burns.py` — `still_to_clip()`
- `src/yt_auto/agents/sources.py` — `SceneSource` protocol, `SceneSourceError`, `LocalDiffusionSource`, `PexelsSource`
- `docs/comfyui-setup.md` — install + run guide
- `tests/unit/test_comfyui_client.py`
- `tests/unit/test_ffmpeg_ken_burns.py`
- `tests/unit/test_scene_sources.py`
- `tests/fixtures/comfyui_history_done.json`
- `tests/fixtures/sample_still.png` — a tiny generated 64×64 PNG for Ken Burns tests

**Modify:**
- `src/yt_auto/config.py` — add `comfyui_url`, `media_source`
- `src/yt_auto/prompts/templates/scene_visuals.j2` — ask for `image_prompt` and `video_style`
- `src/yt_auto/prompts/script_meta.py` — pass through `video_style` from response (no signature change to render fn)
- `src/yt_auto/agents/script.py` — merge `image_prompt` + extract `video_style` into `script.json`
- `src/yt_auto/agents/media.py` — rewrite to use `SceneSource` strategy with fallback
- `src/yt_auto/cli.py` — `build_media_agent` constructs both sources, picks primary from config
- `tests/unit/test_media_agent.py` — rewrite around the strategy pattern (some old tests removed/moved)
- `tests/unit/test_script_agent.py` — assert new fields
- `tests/fixtures/gemini_scene_visuals_response.json` — add new fields
- `.gitignore` — add `third_party/`

---

## Task 1: Add config keys

**Files:**
- Modify: `src/yt_auto/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
def test_comfyui_url_default() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.comfyui_url == "http://127.0.0.1:8188"


def test_media_source_default() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.media_source == "local_diffusion"


def test_media_source_accepts_pexels() -> None:
    s = Settings(media_source="pexels", _env_file=None)  # type: ignore[call-arg]
    assert s.media_source == "pexels"


def test_media_source_rejects_garbage() -> None:
    with pytest.raises(ValidationError):
        Settings(media_source="bogus", _env_file=None)  # type: ignore[call-arg]
```

If `pytest` and `ValidationError` aren't imported in that file, add at top:
```python
import pytest
from pydantic import ValidationError
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v -k "comfyui or media_source"`
Expected: 4 FAIL with AttributeError or ValidationError.

- [ ] **Step 3: Add the config fields**

In `src/yt_auto/config.py`, inside the `Settings` class, after the Pexels block:

```python
    # B-roll source
    media_source: Literal["local_diffusion", "pexels"] = Field(default="local_diffusion")
    comfyui_url: str = Field(default="http://127.0.0.1:8188")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/config.py tests/unit/test_config.py
git commit -m "config: add comfyui_url and media_source settings"
```

---

## Task 2: SDXL workflow JSON template

**Files:**
- Create: `src/yt_auto/clients/workflows/__init__.py`
- Create: `src/yt_auto/clients/workflows/sdxl_txt2img.json`

This is the static ComfyUI workflow that `ComfyUIClient` will fill in. ComfyUI's `/prompt` endpoint accepts a JSON dict keyed by integer node ids. The placeholders `PROMPT_PLACEHOLDER`, `WIDTH_PLACEHOLDER`, `HEIGHT_PLACEHOLDER`, `SEED_PLACEHOLDER` will be replaced by the client per request.

- [ ] **Step 1: Create the workflows package marker**

Create `src/yt_auto/clients/workflows/__init__.py` as an empty file (so the JSON is installable as package data).

- [ ] **Step 2: Create the workflow JSON**

Create `src/yt_auto/clients/workflows/sdxl_txt2img.json` with:

```json
{
  "3": {
    "class_type": "KSampler",
    "inputs": {
      "seed": "SEED_PLACEHOLDER",
      "steps": 25,
      "cfg": 7.0,
      "sampler_name": "euler",
      "scheduler": "normal",
      "denoise": 1.0,
      "model": ["4", 0],
      "positive": ["6", 0],
      "negative": ["7", 0],
      "latent_image": ["5", 0]
    }
  },
  "4": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
  },
  "5": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": "WIDTH_PLACEHOLDER", "height": "HEIGHT_PLACEHOLDER", "batch_size": 1}
  },
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "PROMPT_PLACEHOLDER", "clip": ["4", 1]}
  },
  "7": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "low quality, blurry, deformed, watermark, text, logo", "clip": ["4", 1]}
  },
  "8": {
    "class_type": "VAEDecode",
    "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
  },
  "9": {
    "class_type": "SaveImage",
    "inputs": {"filename_prefix": "yt_auto", "images": ["8", 0]}
  }
}
```

- [ ] **Step 3: Verify pyproject ships it as package data**

Run: `cat pyproject.toml | grep -A5 "package-data\|include"`

If there's no explicit package-data config and the build backend is hatch / setuptools / uv-build with src layout, JSON files inside the package are typically included by default. If you find the build excludes non-`.py`, add appropriate package-data config — but most likely no change is needed. Confirm by running:

```bash
uv build --wheel 2>&1 | tail -5
python -c "import importlib.resources, yt_auto.clients.workflows as w; print(list(importlib.resources.files(w).iterdir()))"
```

Expected: the iter output includes `sdxl_txt2img.json`.

- [ ] **Step 4: Commit**

```bash
git add src/yt_auto/clients/workflows/
git commit -m "comfyui: add SDXL txt2img workflow template"
```

---

## Task 3: ComfyUIClient — submit + poll

**Files:**
- Create: `src/yt_auto/clients/comfyui.py`
- Create: `tests/fixtures/comfyui_history_done.json`
- Create: `tests/unit/test_comfyui_client.py`

- [ ] **Step 1: Create the history fixture**

Create `tests/fixtures/comfyui_history_done.json`:

```json
{
  "PROMPT_ID_HERE": {
    "prompt": [],
    "outputs": {
      "9": {
        "images": [
          {"filename": "yt_auto_00001_.png", "subfolder": "", "type": "output"}
        ]
      }
    },
    "status": {"completed": true}
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_comfyui_client.py`:

```python
"""Tests for ComfyUIClient. All HTTP is faked via httpx MockTransport."""

import json
from pathlib import Path

import httpx
import pytest

from yt_auto.clients.comfyui import ComfyUIClient, ComfyUIError

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _history_payload(prompt_id: str) -> dict:
    raw = json.loads((FIXTURE_DIR / "comfyui_history_done.json").read_text())
    return {prompt_id: raw["PROMPT_ID_HERE"]}


def test_workflow_template_substitutes_prompt_dims_seed() -> None:
    client = ComfyUIClient(base_url="http://x")
    wf = client._build_workflow(prompt="a cat", width=1024, height=768, seed=42)
    assert wf["5"]["inputs"]["width"] == 1024
    assert wf["5"]["inputs"]["height"] == 768
    assert wf["3"]["inputs"]["seed"] == 42
    assert wf["6"]["inputs"]["text"] == "a cat"


@pytest.mark.asyncio
async def test_generate_image_happy_path(tmp_path: Path) -> None:
    prompt_id = "abc-123"
    calls: list[tuple[str, str]] = []
    png_bytes = b"\x89PNG\r\n\x1a\nFAKEPNG"

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if req.method == "GET" and req.url.path == f"/history/{prompt_id}":
            return httpx.Response(200, json=_history_payload(prompt_id))
        if req.method == "GET" and req.url.path == "/view":
            return httpx.Response(200, content=png_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)

    dest = tmp_path / "out.png"
    await client.generate_image(
        prompt="majestic mountain", width=1024, height=1024, seed=7, dest=dest
    )

    assert dest.read_bytes() == png_bytes
    assert ("POST", "/prompt") in calls
    assert ("GET", f"/history/{prompt_id}") in calls
    assert ("GET", "/view") in calls


@pytest.mark.asyncio
async def test_generate_image_polls_until_done(tmp_path: Path) -> None:
    prompt_id = "abc-123"
    history_calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal history_calls
        if req.method == "POST" and req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id})
        if req.method == "GET" and req.url.path == f"/history/{prompt_id}":
            history_calls += 1
            if history_calls < 3:
                return httpx.Response(200, json={})  # not done yet
            return httpx.Response(200, json=_history_payload(prompt_id))
        if req.method == "GET" and req.url.path == "/view":
            return httpx.Response(200, content=b"PNG")
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)
    dest = tmp_path / "out.png"
    await client.generate_image(prompt="x", width=64, height=64, seed=1, dest=dest)
    assert history_calls == 3


@pytest.mark.asyncio
async def test_generate_image_raises_on_submit_failure(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http, poll_interval_s=0.0)
    with pytest.raises(ComfyUIError, match="submit"):
        await client.generate_image(
            prompt="x", width=64, height=64, seed=1, dest=tmp_path / "out.png"
        )


@pytest.mark.asyncio
async def test_generate_image_raises_on_poll_timeout(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json={"prompt_id": "abc"})
        return httpx.Response(200, json={})  # always pending

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(
        base_url="http://comfy", _http=http, poll_interval_s=0.0, timeout_s=0.05
    )
    with pytest.raises(ComfyUIError, match="timeout"):
        await client.generate_image(
            prompt="x", width=64, height=64, seed=1, dest=tmp_path / "out.png"
        )


@pytest.mark.asyncio
async def test_ping_returns_true_when_reachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http)
    assert await client.ping() is True


@pytest.mark.asyncio
async def test_ping_returns_false_when_unreachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://comfy")
    client = ComfyUIClient(base_url="http://comfy", _http=http)
    assert await client.ping() is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_comfyui_client.py -v`
Expected: ImportError — `comfyui` module not found.

- [ ] **Step 4: Implement the client**

Create `src/yt_auto/clients/comfyui.py`:

```python
"""Thin async client for a local ComfyUI server: submit workflow → poll → download PNG."""

import asyncio
import importlib.resources
import json
import time
from pathlib import Path
from typing import Any

import httpx

from yt_auto.logging import get_logger

log = get_logger(__name__)


class ComfyUIError(Exception):
    """ComfyUI request failed or timed out."""


def _load_workflow_template() -> dict[str, Any]:
    res = importlib.resources.files("yt_auto.clients.workflows") / "sdxl_txt2img.json"
    return json.loads(res.read_text(encoding="utf-8"))


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 180.0,
        poll_interval_s: float = 1.0,
        _http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._http = _http or httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        self._template = _load_workflow_template()

    def _build_workflow(
        self, *, prompt: str, width: int, height: int, seed: int
    ) -> dict[str, Any]:
        wf = json.loads(json.dumps(self._template))  # deep copy
        wf["3"]["inputs"]["seed"] = int(seed)
        wf["5"]["inputs"]["width"] = int(width)
        wf["5"]["inputs"]["height"] = int(height)
        wf["6"]["inputs"]["text"] = prompt
        return wf

    async def ping(self) -> bool:
        try:
            resp = await self._http.get("/system_stats", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        dest: Path,
    ) -> None:
        wf = self._build_workflow(prompt=prompt, width=width, height=height, seed=seed)
        try:
            resp = await self._http.post("/prompt", json={"prompt": wf})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"submit failed: {exc}") from exc

        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"submit response missing prompt_id: {resp.text[:200]}")

        image_info = await self._poll_until_done(prompt_id)
        await self._download_image(image_info, dest)
        log.info("comfyui_generated", prompt_id=prompt_id, dest=str(dest))

    async def _poll_until_done(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                resp = await self._http.get(f"/history/{prompt_id}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"poll failed: {exc}") from exc
            data = resp.json()
            entry = data.get(prompt_id)
            if entry and entry.get("outputs"):
                images = self._extract_first_image(entry["outputs"])
                if images is not None:
                    return images
            if time.monotonic() >= deadline:
                raise ComfyUIError(f"timeout waiting for prompt {prompt_id}")
            await asyncio.sleep(self._poll_interval_s)

    @staticmethod
    def _extract_first_image(outputs: dict[str, Any]) -> dict[str, Any] | None:
        for node_output in outputs.values():
            for img in node_output.get("images", []) or []:
                return img  # first image of first node with images
        return None

    async def _download_image(self, image_info: dict[str, Any], dest: Path) -> None:
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        try:
            resp = await self._http.get("/view", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"download failed: {exc}") from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_comfyui_client.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/clients/comfyui.py tests/unit/test_comfyui_client.py tests/fixtures/comfyui_history_done.json
git commit -m "comfyui: add async client for submit/poll/download"
```

---

## Task 4: Ken Burns ffmpeg helper

**Files:**
- Create: `src/yt_auto/ffmpeg/ken_burns.py`
- Create: `tests/fixtures/sample_still.png`
- Create: `tests/unit/test_ffmpeg_ken_burns.py`

This task uses real ffmpeg (like other ffmpeg tests in the repo).

- [ ] **Step 1: Create the sample PNG fixture**

Run from project root:
```bash
uv run python -c "
from PIL import Image
img = Image.new('RGB', (1344, 768), (40, 80, 160))
for x in range(0, 1344, 64):
    for y in range(0, 768, 64):
        img.paste(((x + y) % 256, x % 256, y % 256), (x, y, x + 64, y + 64))
img.save('tests/fixtures/sample_still.png')
"
```

If `Pillow` isn't already a dev dep:
```bash
uv add --dev pillow
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_ffmpeg_ken_burns.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ffmpeg_ken_burns.py -v`
Expected: ImportError — `ken_burns` not found.

- [ ] **Step 4: Implement the helper**

Create `src/yt_auto/ffmpeg/ken_burns.py`:

```python
"""Render a still image into a video clip with a slow ffmpeg zoompan motion."""

import asyncio
from pathlib import Path
from typing import Literal

from yt_auto.ffmpeg.prepare_clip import FFmpegError

Motion = Literal["zoom_in", "zoom_out", "pan_left", "pan_right"]
MOTION_PRESETS: tuple[Motion, ...] = ("zoom_in", "zoom_out", "pan_left", "pan_right")


def pick_motion(seed: int) -> Motion:
    return MOTION_PRESETS[seed % len(MOTION_PRESETS)]


def _build_zoompan_filter(
    *, motion: Motion, total_frames: int, width: int, height: int
) -> str:
    # zoompan operates on every frame; d=1 with a higher-level fps wrapper ensures
    # we get one zoompan step per output frame. Zoom range chosen for a slow,
    # cinematic move (10–20% over the clip).
    z_start = 1.0
    z_end = 1.15
    # zoompan expression `on` is the output frame number.
    if motion == "zoom_in":
        z = f"{z_start}+({z_end - z_start})*on/{max(total_frames - 1, 1)}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "zoom_out":
        z = f"{z_end}-({z_end - z_start})*on/{max(total_frames - 1, 1)}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        z = str(z_end)
        # x goes from right edge to left edge over the clip.
        x = f"(iw-iw/zoom)*(1-on/{max(total_frames - 1, 1)})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z = str(z_end)
        x = f"(iw-iw/zoom)*on/{max(total_frames - 1, 1)}"
        y = "ih/2-(ih/zoom/2)"
    else:
        raise AssertionError(f"unknown motion {motion}")
    return (
        f"scale=8000:-2,"  # upscale source first so zoompan output is smooth
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:fps={total_frames}:s={width}x{height}"
    )


async def still_to_clip(
    *,
    src: Path,
    dest: Path,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    seed: int,
) -> None:
    """Render `src` as a `duration_s` clip at `width`x`height`@`fps` with motion."""
    motion = pick_motion(seed)
    total_frames = max(int(round(duration_s * fps)), 1)
    # ffmpeg's zoompan needs to know how many frames to emit; we pass it via the
    # filter (fps=total_frames means "emit this many frames per second of zoompan
    # virtual time") and constrain output duration with -t.
    vf = _build_zoompan_filter(
        motion=motion, total_frames=total_frames, width=width, height=height
    )
    vf_full = f"{vf},fps={fps},setsar=1,format=yuv420p"

    args: list[str] = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(src),
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        vf_full,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "20",
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
            f"still_to_clip failed for {src} (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace').strip()[-500:]}"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ffmpeg_ken_burns.py -v`
Expected: all PASS (skipped if no ffmpeg).

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/ffmpeg/ken_burns.py tests/unit/test_ffmpeg_ken_burns.py tests/fixtures/sample_still.png
git commit -m "ffmpeg: add Ken Burns still-to-clip helper"
```

---

## Task 5: SceneSource protocol + extract PexelsSource

This task introduces the strategy interface and moves the existing Pexels logic behind it. The current `MediaAgent` is not yet rewritten — that's Task 7.

**Files:**
- Create: `src/yt_auto/agents/sources.py`
- Create: `tests/unit/test_scene_sources.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_scene_sources.py`:

```python
"""Tests for SceneSource protocol implementations."""

from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.sources import PexelsSource, SceneSourceError
from yt_auto.clients.pexels import Clip


class _FakePexels:
    def __init__(self, results: list[Clip]) -> None:
        self._results = results
        self.searches: list[str] = []
        self.downloads: list[tuple[str, Path]] = []

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        self.searches.append(query)
        return self._results

    async def download(self, *, url: str, dest: Path) -> None:
        self.downloads.append((url, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE")


def _scene(**overrides: Any) -> dict[str, Any]:
    base = {
        "index": 0,
        "start_s": 0.0,
        "end_s": 4.0,
        "narration_excerpt": "x",
        "visual_prompt": "x",
        "image_prompt": "a mountain at sunset, dramatic light",
        "pexels_query": "mountain sunset",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_pexels_source_searches_downloads_prepares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakePexels(
        [Clip(id=1, duration_s=10, width=1920, height=1080, url="http://x/a.mp4")]
    )
    prepare_calls: list[dict[str, Any]] = []

    async def fake_prepare(**kwargs: Any) -> None:
        prepare_calls.append(kwargs)
        kwargs["dest"].write_bytes(b"PREPARED")

    monkeypatch.setattr("yt_auto.agents.sources.prepare_clip", fake_prepare)

    source = PexelsSource(pexels=fake, per_page=10)
    dest = tmp_path / "scene_000.mp4"
    await source.produce_clip(
        scene=_scene(),
        target_duration_s=4.0,
        width=1920,
        height=1080,
        fps=30,
        dest=dest,
    )

    assert fake.searches == ["mountain sunset"]
    assert len(fake.downloads) == 1
    assert prepare_calls[0]["target_duration_s"] == 4.0
    assert prepare_calls[0]["dest"] == dest


@pytest.mark.asyncio
async def test_pexels_source_raises_on_no_clips(tmp_path: Path) -> None:
    fake = _FakePexels([])
    source = PexelsSource(pexels=fake, per_page=10)
    with pytest.raises(SceneSourceError, match="no clips"):
        await source.produce_clip(
            scene=_scene(),
            target_duration_s=4.0,
            width=1920,
            height=1080,
            fps=30,
            dest=tmp_path / "out.mp4",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_scene_sources.py -v`
Expected: ImportError — `sources` not found.

- [ ] **Step 3: Implement the protocol + PexelsSource**

Create `src/yt_auto/agents/sources.py`:

```python
"""Pluggable per-scene clip producers used by MediaAgent.

Each SceneSource takes a scene dict + target dims/duration and writes a
normalized .mp4 to `dest`. Any failure raises SceneSourceError; the agent
catches that and tries the next source in line.
"""

from pathlib import Path
from typing import Any, Protocol

from yt_auto.clients.pexels import Clip
from yt_auto.ffmpeg.prepare_clip import prepare_clip
from yt_auto.logging import get_logger

log = get_logger(__name__)


class SceneSourceError(Exception):
    """A per-scene clip producer could not produce a clip."""


class PexelsLike(Protocol):
    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]: ...
    async def download(self, *, url: str, dest: Path) -> None: ...


class SceneSource(Protocol):
    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None: ...


def _pick_best_clip(clips: list[Clip], *, target_duration_s: float) -> Clip:
    if not clips:
        raise SceneSourceError("no clips returned from Pexels for this scene")
    qualifying = [c for c in clips if c.duration_s >= target_duration_s]
    if qualifying:
        return min(qualifying, key=lambda c: c.duration_s)
    return max(clips, key=lambda c: c.duration_s)


class PexelsSource:
    """Search Pexels for the scene's pexels_query, pick best clip, normalize."""

    def __init__(self, pexels: PexelsLike, *, per_page: int = 10) -> None:
        self._pexels = pexels
        self._per_page = per_page

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        query: str = scene["pexels_query"]
        try:
            clips = await self._pexels.search_videos(query=query, per_page=self._per_page)
            picked = _pick_best_clip(clips, target_duration_s=target_duration_s)
            raw_path = dest.with_name(dest.stem + "_raw.mp4")
            await self._pexels.download(url=picked.url, dest=raw_path)
            await prepare_clip(
                src=raw_path,
                dest=dest,
                target_duration_s=target_duration_s,
                width=width,
                height=height,
                fps=fps,
            )
        except SceneSourceError:
            raise
        except Exception as exc:  # noqa: BLE001 — translate any I/O / ffmpeg failure
            raise SceneSourceError(f"pexels source failed: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_scene_sources.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/agents/sources.py tests/unit/test_scene_sources.py
git commit -m "agents: extract PexelsSource behind SceneSource protocol"
```

---

## Task 6: LocalDiffusionSource

**Files:**
- Modify: `src/yt_auto/agents/sources.py` (add class)
- Modify: `tests/unit/test_scene_sources.py` (add tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_scene_sources.py`:

```python
from yt_auto.agents.sources import LocalDiffusionSource


class _FakeComfy:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def generate_image(
        self, *, prompt: str, width: int, height: int, seed: int, dest: Path
    ) -> None:
        self.calls.append(
            {"prompt": prompt, "width": width, "height": height, "seed": seed, "dest": dest}
        )
        if self._fail:
            from yt_auto.clients.comfyui import ComfyUIError
            raise ComfyUIError("simulated")
        # Write a real PNG-shaped file so Ken Burns can read it.
        # Tests below stub still_to_clip so the bytes don't actually need to be valid PNG.
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")


@pytest.mark.asyncio
async def test_local_diffusion_source_appends_video_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_comfy = _FakeComfy()
    kb_calls: list[dict[str, Any]] = []

    async def fake_kb(**kwargs: Any) -> None:
        kb_calls.append(kwargs)
        kwargs["dest"].write_bytes(b"CLIP")

    monkeypatch.setattr("yt_auto.agents.sources.still_to_clip", fake_kb)

    source = LocalDiffusionSource(
        comfyui=fake_comfy, video_style="cinematic photography, 35mm film"
    )
    dest = tmp_path / "scene_000.mp4"
    await source.produce_clip(
        scene=_scene(image_prompt="a lone monk on a mountain"),
        target_duration_s=4.0,
        width=1920,
        height=1080,
        fps=30,
        dest=dest,
    )

    assert len(fake_comfy.calls) == 1
    sent = fake_comfy.calls[0]
    assert sent["prompt"] == (
        "a lone monk on a mountain, cinematic photography, 35mm film"
    )
    # SDXL-native landscape dims for 16:9 target.
    assert sent["width"] == 1344
    assert sent["height"] == 768
    # Ken Burns called with the generated PNG path and target output dims.
    assert kb_calls[0]["width"] == 1920
    assert kb_calls[0]["height"] == 1080
    assert kb_calls[0]["duration_s"] == 4.0


@pytest.mark.asyncio
async def test_local_diffusion_source_uses_portrait_gen_dims_for_vertical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_comfy = _FakeComfy()

    async def fake_kb(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"CLIP")

    monkeypatch.setattr("yt_auto.agents.sources.still_to_clip", fake_kb)

    source = LocalDiffusionSource(comfyui=fake_comfy, video_style="x")
    await source.produce_clip(
        scene=_scene(),
        target_duration_s=4.0,
        width=1080,
        height=1920,
        fps=30,
        dest=tmp_path / "out.mp4",
    )
    sent = fake_comfy.calls[0]
    assert sent["width"] == 768
    assert sent["height"] == 1344


@pytest.mark.asyncio
async def test_local_diffusion_source_raises_on_comfyui_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_comfy = _FakeComfy(fail=True)

    async def fake_kb(**kwargs: Any) -> None:
        pass

    monkeypatch.setattr("yt_auto.agents.sources.still_to_clip", fake_kb)

    source = LocalDiffusionSource(comfyui=fake_comfy, video_style="x")
    with pytest.raises(SceneSourceError, match="comfyui"):
        await source.produce_clip(
            scene=_scene(),
            target_duration_s=4.0,
            width=1920,
            height=1080,
            fps=30,
            dest=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_local_diffusion_source_seeds_from_scene_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_comfy = _FakeComfy()

    async def fake_kb(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"CLIP")

    monkeypatch.setattr("yt_auto.agents.sources.still_to_clip", fake_kb)
    source = LocalDiffusionSource(comfyui=fake_comfy, video_style="x")
    await source.produce_clip(
        scene=_scene(index=7),
        target_duration_s=4.0,
        width=1920,
        height=1080,
        fps=30,
        dest=tmp_path / "out.mp4",
    )
    assert fake_comfy.calls[0]["seed"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_scene_sources.py -v -k local_diffusion`
Expected: ImportError — `LocalDiffusionSource` not found.

- [ ] **Step 3: Extend `sources.py`**

Add to `src/yt_auto/agents/sources.py` (append at the bottom; also add the new imports at the top):

```python
# Add near top, after other imports:
from yt_auto.clients.comfyui import ComfyUIClient, ComfyUIError
from yt_auto.ffmpeg.ken_burns import still_to_clip

# SDXL-native generation dimensions, chosen to match output aspect ratio.
# Anything close to 1024x1024 area; these are the standard SDXL ratios.
_GEN_DIMS_LANDSCAPE = (1344, 768)
_GEN_DIMS_PORTRAIT = (768, 1344)


class ComfyLike(Protocol):
    async def generate_image(
        self, *, prompt: str, width: int, height: int, seed: int, dest: Path
    ) -> None: ...


class LocalDiffusionSource:
    """Generate a still via ComfyUI, then animate it with Ken Burns."""

    def __init__(self, comfyui: ComfyLike, *, video_style: str) -> None:
        self._comfyui = comfyui
        self._video_style = video_style

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        image_prompt = scene["image_prompt"]
        full_prompt = f"{image_prompt}, {self._video_style}"
        gen_w, gen_h = _GEN_DIMS_LANDSCAPE if width >= height else _GEN_DIMS_PORTRAIT
        seed = int(scene["index"])
        png_path = dest.with_name(dest.stem + ".png")
        try:
            await self._comfyui.generate_image(
                prompt=full_prompt, width=gen_w, height=gen_h, seed=seed, dest=png_path
            )
            await still_to_clip(
                src=png_path,
                dest=dest,
                duration_s=target_duration_s,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
            )
        except ComfyUIError as exc:
            raise SceneSourceError(f"comfyui generation failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise SceneSourceError(f"local diffusion failed: {exc}") from exc
```

Note: `ComfyUIClient` itself satisfies `ComfyLike` structurally; the import is for type clarity and the `ComfyUIError` translation. The `ComfyUIClient` class can still be passed directly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_scene_sources.py -v`
Expected: all PASS (both Pexels and LocalDiffusion groups).

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/agents/sources.py tests/unit/test_scene_sources.py
git commit -m "agents: add LocalDiffusionSource (ComfyUI + Ken Burns)"
```

---

## Task 7: Script Agent — image_prompt + video_style

**Files:**
- Modify: `src/yt_auto/prompts/templates/scene_visuals.j2`
- Modify: `src/yt_auto/agents/script.py`
- Modify: `tests/fixtures/gemini_scene_visuals_response.json`
- Modify: `tests/unit/test_script_agent.py`

- [ ] **Step 1: Update the fixture to the new response shape**

Overwrite `tests/fixtures/gemini_scene_visuals_response.json`:

```json
{
  "video_style": "cinematic photography, 35mm film, dramatic natural lighting, shallow depth of field, photorealistic",
  "scenes": [
    {
      "index": 0,
      "visual_prompt": "lone figure approaches old city gates at sunrise",
      "image_prompt": "a lone hooded traveler approaches massive stone city gates at golden hour, long shadows, golden light catching dust",
      "pexels_query": "traveler city gates sunrise"
    },
    {
      "index": 1,
      "visual_prompt": "narrow cobblestone streets coming alive with morning light",
      "image_prompt": "narrow medieval cobblestone street at dawn, warm light spilling from open shutters, wet stones reflecting the sky",
      "pexels_query": "cobblestone street morning"
    },
    {
      "index": 2,
      "visual_prompt": "close-up of polished copper espresso pots venting steam",
      "image_prompt": "extreme close-up of polished copper espresso pots venting fine white steam against a dark backdrop, soft rim light",
      "pexels_query": "copper espresso steam closeup"
    },
    {
      "index": 3,
      "visual_prompt": "barista pours rich crema into a small white cup",
      "image_prompt": "an espresso shot pouring into a small white ceramic cup, thick golden crema, soft window light, shallow focus",
      "pexels_query": "barista pouring espresso crema"
    }
  ]
}
```

- [ ] **Step 2: Write the failing script-agent test**

Append to `tests/unit/test_script_agent.py`:

```python
@pytest.mark.asyncio
async def test_script_json_has_image_prompt_and_video_style(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)
    result = await agent.run(_ctx(tmp_path))
    data = json.loads(result.artifacts["script.json"].read_text())

    assert data["video_style"] == scene_visuals_fixture["video_style"]
    for scene in data["scenes"]:
        assert isinstance(scene["image_prompt"], str)
        assert len(scene["image_prompt"]) > 0
```

Also update the existing `test_script_agent_computes_scene_timings_from_word_counts` assertion loop near the bottom of that test (the `for sc in scenes:` block, currently asserting `visual_prompt` + `pexels_query`) to also require `image_prompt`:

```python
    for sc in scenes:
        assert "visual_prompt" in sc
        assert "image_prompt" in sc
        assert "pexels_query" in sc
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_script_agent.py -v -k image_prompt`
Expected: FAIL (KeyError on `video_style` or `image_prompt`).

- [ ] **Step 4: Update the Jinja template**

Overwrite `src/yt_auto/prompts/templates/scene_visuals.j2`:

```jinja
You are a visual director for a narrated video. Pick ONE coherent visual style for
the entire video (a 6-12 word phrase like "cinematic photography, 35mm film,
dramatic natural lighting, shallow depth of field, photorealistic" or "moody oil
painting, thick brushwork, warm amber palette, romanticist composition"), then for
each scene write three things:

- visual_prompt: 1-2 sentence concrete description of what should appear (used by humans only)
- image_prompt: vivid Stable Diffusion-style prompt describing subject, composition,
  lighting, and mood — DO NOT include the global style; it will be appended
  automatically. 1-3 sentences, no quotes.
- pexels_query: 3-6 keywords suitable for searching Pexels stock footage (fallback path)

SCENES:
{% for scene in scenes %}
- Scene {{ scene.index }}: {{ scene.narration_excerpt }}
{% endfor %}

OUTPUT FORMAT: a single JSON object, no prose around it, matching:
{
  "video_style": "<6-12 word style phrase>",
  "scenes": [
    {"index": 0, "visual_prompt": "<...>", "image_prompt": "<...>", "pexels_query": "<...>"}
  ]
}

Return exactly one entry per input scene, in the same order, with matching indexes.
```

- [ ] **Step 5: Update `script.py` merge logic**

In `src/yt_auto/agents/script.py`, find `_merge_visuals` and the place the `script` dict is assembled. Update `_merge_visuals` to also pull `image_prompt`:

```python
    @staticmethod
    def _merge_visuals(
        timed: list[dict[str, Any]], visuals: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_index = {v["index"]: v for v in visuals}
        out: list[dict[str, Any]] = []
        for scene in timed:
            v = by_index.get(scene["index"])
            if v is None:
                raise ValueError(f"visuals response missing scene index {scene['index']}")
            out.append(
                {
                    **scene,
                    "visual_prompt": v["visual_prompt"],
                    "image_prompt": v["image_prompt"],
                    "pexels_query": v["pexels_query"],
                }
            )
        return out
```

And in the `run` method, where the `script` dict is built (around line 59-68), pull `video_style` out of the visuals response and include it:

```python
        visuals_data = await self._gemini.generate_json(
            render_scene_visuals_prompt(scenes=scenes_timed)
        )
        scenes_with_visuals = self._merge_visuals(scenes_timed, visuals_data["scenes"])
        video_style = visuals_data.get("video_style", "")

        script = {
            "topic": ctx.topic,
            "format": ctx.format,
            "voice_category": params.voice_category,
            "duration_target_s": target_duration_seconds(ctx.format),
            "video_style": video_style,
            "narration": narration_data["narration"],
            "scenes": scenes_with_visuals,
            "youtube": narration_data["youtube"],
            "prompt_params": params.to_dict(),
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_script_agent.py -v`
Expected: all PASS. Also run `uv run pytest tests/unit/test_prompt_templates.py -v` — if a snapshot test exists for the template, update it.

- [ ] **Step 7: Commit**

```bash
git add src/yt_auto/prompts/templates/scene_visuals.j2 src/yt_auto/agents/script.py tests/fixtures/gemini_scene_visuals_response.json tests/unit/test_script_agent.py
git commit -m "script: emit image_prompt per scene and video_style at script level"
```

---

## Task 8: MediaAgent rewrite with fallback

**Files:**
- Modify: `src/yt_auto/agents/media.py`
- Modify: `tests/unit/test_media_agent.py`

- [ ] **Step 1: Rewrite the media-agent tests**

Replace the contents of `tests/unit/test_media_agent.py` with:

```python
"""Tests for the strategy-based MediaAgent."""

import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.media import MediaAgent, MediaError, rescale_scenes
from yt_auto.agents.sources import SceneSource, SceneSourceError
from yt_auto.pipeline.context import RunContext


def test_rescale_scenes_preserves_relative_proportions() -> None:
    scenes = [
        {"index": 0, "start_s": 0.0, "end_s": 10.0, "narration_excerpt": "a"},
        {"index": 1, "start_s": 10.0, "end_s": 30.0, "narration_excerpt": "b"},
        {"index": 2, "start_s": 30.0, "end_s": 50.0, "narration_excerpt": "c"},
    ]
    rescaled = rescale_scenes(scenes, target_total_duration_s=25.0)
    assert rescaled[0]["end_s"] == pytest.approx(5.0)
    assert rescaled[1]["end_s"] == pytest.approx(15.0)
    assert rescaled[2]["end_s"] == pytest.approx(25.0)


class _RecordingSource:
    def __init__(self, *, fail_on_indexes: set[int] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_on = fail_on_indexes or set()

    async def produce_clip(
        self,
        *,
        scene: dict[str, Any],
        target_duration_s: float,
        width: int,
        height: int,
        fps: int,
        dest: Path,
    ) -> None:
        self.calls.append({"index": scene["index"], "dest": dest})
        if scene["index"] in self._fail_on:
            raise SceneSourceError(f"forced failure for scene {scene['index']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"CLIP")


def _make_ctx(tmp_path: Path, *, video_style: str = "x") -> RunContext:
    script = tmp_path / "script.json"
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"fake")
    script.write_text(
        json.dumps(
            {
                "format": "short",
                "video_style": video_style,
                "scenes": [
                    {
                        "index": 0,
                        "start_s": 0.0,
                        "end_s": 5.0,
                        "narration_excerpt": "a",
                        "visual_prompt": "x",
                        "image_prompt": "a sunset over a beach",
                        "pexels_query": "sunset beach",
                    },
                    {
                        "index": 1,
                        "start_s": 5.0,
                        "end_s": 10.0,
                        "narration_excerpt": "b",
                        "visual_prompt": "y",
                        "image_prompt": "a mountain trail at dawn",
                        "pexels_query": "mountain trail",
                    },
                ],
            }
        )
    )
    return RunContext(
        run_id="r",
        topic="t",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": script, "voice.mp3": voice},
        metadata={"actual_duration_s": 8.0},
    )


@pytest.mark.asyncio
async def test_media_agent_uses_primary_when_all_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=fallback)
    result = await agent.run(_make_ctx(tmp_path))

    assert [c["index"] for c in primary.calls] == [0, 1]
    assert fallback.calls == []
    assert result.metadata["clip_count"] == 2
    assert result.metadata["source_counts"] == {"primary": 2, "fallback": 0}


@pytest.mark.asyncio
async def test_media_agent_falls_back_per_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource(fail_on_indexes={1})
    fallback = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=fallback)
    result = await agent.run(_make_ctx(tmp_path))

    # Primary attempted both scenes.
    assert [c["index"] for c in primary.calls] == [0, 1]
    # Fallback only invoked for scene 1.
    assert [c["index"] for c in fallback.calls] == [1]
    assert result.metadata["source_counts"] == {"primary": 1, "fallback": 1}


@pytest.mark.asyncio
async def test_media_agent_raises_when_both_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource(fail_on_indexes={0})
    fallback = _RecordingSource(fail_on_indexes={0})
    monkeypatch.setattr(
        "yt_auto.agents.media.concat_clips",
        lambda **k: (_ for _ in ()).throw(AssertionError("should not concat")),
    )
    agent = MediaAgent(primary=primary, fallback=fallback)
    with pytest.raises(MediaError, match="both sources"):
        await agent.run(_make_ctx(tmp_path))


@pytest.mark.asyncio
async def test_media_agent_works_with_only_one_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=primary, fallback=None)
    result = await agent.run(_make_ctx(tmp_path))
    assert result.metadata["source_counts"]["primary"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_media_agent.py -v`
Expected: FAIL — old `MediaAgent(pexels=...)` constructor signature, missing `source_counts`, etc.

- [ ] **Step 3: Rewrite the MediaAgent**

Replace the contents of `src/yt_auto/agents/media.py` with:

```python
"""Media Agent: produce a normalized clip per scene via pluggable SceneSources, then concat."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from yt_auto.agents.sources import SceneSource, SceneSourceError
from yt_auto.ffmpeg.concat import concat_clips
from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30

# A primary may be a SceneSource directly, or a factory that takes the script's
# video_style and returns a SceneSource. The factory form lets LocalDiffusionSource
# bind to a style read from script.json at run time without leaking script state
# into the CLI wiring.
PrimaryArg = SceneSource | Callable[[str], SceneSource]


class MediaError(Exception):
    """Could not produce video_silent.mp4."""


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
    rescaled[-1]["end_s"] = target_total_duration_s
    return rescaled


def _resolve_primary(arg: PrimaryArg, video_style: str) -> SceneSource:
    # A SceneSource has produce_clip; a factory is callable but lacks it.
    if hasattr(arg, "produce_clip"):
        return arg  # type: ignore[return-value]
    return arg(video_style)  # type: ignore[operator]


class MediaAgent:
    name = "media"

    def __init__(
        self, *, primary: PrimaryArg, fallback: SceneSource | None = None
    ) -> None:
        self._primary_arg = primary
        self._fallback = fallback

    async def run(self, ctx: RunContext) -> StageResult:
        script = json.loads(ctx.artifacts["script.json"].read_text())
        video_style = script.get("video_style", "")
        primary = _resolve_primary(self._primary_arg, video_style)

        actual_voice_duration = ctx.metadata.get("actual_duration_s")
        if actual_voice_duration is None:
            actual_voice_duration = await probe_duration_s(ctx.artifacts["voice.mp3"])
        scenes = rescale_scenes(script["scenes"], target_total_duration_s=actual_voice_duration)
        fmt: Literal["long", "short"] = script["format"]
        width, height = _DIMS_BY_FORMAT[fmt]

        footage_dir = ctx.run_dir / "footage"
        footage_dir.mkdir(parents=True, exist_ok=True)
        prepared_paths: list[Path] = []
        counts = {"primary": 0, "fallback": 0}

        for scene in scenes:
            target = float(scene["end_s"] - scene["start_s"])
            dest = footage_dir / f"scene_{scene['index']:03d}.mp4"
            try:
                await primary.produce_clip(
                    scene=scene,
                    target_duration_s=target,
                    width=width,
                    height=height,
                    fps=_FPS,
                    dest=dest,
                )
                counts["primary"] += 1
            except SceneSourceError as exc:
                log.warning(
                    "primary_source_failed",
                    scene_index=scene["index"],
                    error=str(exc),
                )
                if self._fallback is None:
                    raise MediaError(
                        f"primary failed on scene {scene['index']} and no fallback configured: {exc}"
                    ) from exc
                try:
                    await self._fallback.produce_clip(
                        scene=scene,
                        target_duration_s=target,
                        width=width,
                        height=height,
                        fps=_FPS,
                        dest=dest,
                    )
                    counts["fallback"] += 1
                except SceneSourceError as exc2:
                    raise MediaError(
                        f"both sources failed on scene {scene['index']}: "
                        f"primary={exc}; fallback={exc2}"
                    ) from exc2

            prepared_paths.append(dest)

        dest_video = ctx.run_dir / "video_silent.mp4"
        await concat_clips(clips=prepared_paths, dest=dest_video)
        log.info(
            "media_done",
            path=str(dest_video),
            clips=len(prepared_paths),
            source_counts=counts,
        )

        return StageResult(
            artifacts={"video_silent.mp4": dest_video},
            metadata={"clip_count": len(prepared_paths), "source_counts": counts},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_media_agent.py tests/unit/test_scene_sources.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/agents/media.py tests/unit/test_media_agent.py
git commit -m "media: rewrite around SceneSource strategy with per-scene fallback"
```

---

## Task 9: Startup health-check for primary source

Per spec §7 / §9: if ComfyUI is unreachable at run start, skip primary entirely and use the fallback for every scene. This saves N HTTP timeouts (one per scene) on a structural failure.

**Files:**
- Modify: `src/yt_auto/agents/media.py`
- Modify: `tests/unit/test_media_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_media_agent.py`:

```python
@pytest.mark.asyncio
async def test_media_agent_skips_primary_when_healthcheck_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def failing_healthcheck() -> bool:
        return False

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(
        primary=primary, fallback=fallback, primary_healthcheck=failing_healthcheck
    )
    result = await agent.run(_make_ctx(tmp_path))

    assert primary.calls == []  # never invoked
    assert [c["index"] for c in fallback.calls] == [0, 1]
    assert result.metadata["source_counts"] == {"primary": 0, "fallback": 2}
    assert result.metadata["primary_healthy"] is False


@pytest.mark.asyncio
async def test_media_agent_uses_primary_when_healthcheck_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _RecordingSource()
    fallback = _RecordingSource()

    async def ok_healthcheck() -> bool:
        return True

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(
        primary=primary, fallback=fallback, primary_healthcheck=ok_healthcheck
    )
    result = await agent.run(_make_ctx(tmp_path))
    assert [c["index"] for c in primary.calls] == [0, 1]
    assert result.metadata["primary_healthy"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_media_agent.py -v -k healthcheck`
Expected: FAIL — `MediaAgent.__init__` does not accept `primary_healthcheck`.

- [ ] **Step 3: Update MediaAgent**

Edit `src/yt_auto/agents/media.py`. Extend the imports (Callable is already imported from Task 8):

```python
from collections.abc import Awaitable, Callable
```

Add a `primary_healthcheck` parameter to `MediaAgent.__init__`:

```python
    def __init__(
        self,
        *,
        primary: PrimaryArg,
        fallback: SceneSource | None = None,
        primary_healthcheck: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._primary_arg = primary
        self._fallback = fallback
        self._primary_healthcheck = primary_healthcheck
```

Update `MediaAgent.run` to call the healthcheck once at startup. Insert immediately after `primary = _resolve_primary(self._primary_arg, video_style)` and before the per-scene loop:

```python
        primary_healthy = True
        if self._primary_healthcheck is not None:
            primary_healthy = await self._primary_healthcheck()
            if not primary_healthy:
                log.warning("primary_source_unreachable_using_fallback")
                if self._fallback is None:
                    raise MediaError(
                        "primary healthcheck failed and no fallback configured"
                    )
```

Then in the per-scene loop, when `primary_healthy is False`, skip directly to fallback without trying primary:

```python
        for scene in scenes:
            target = float(scene["end_s"] - scene["start_s"])
            dest = footage_dir / f"scene_{scene['index']:03d}.mp4"

            if not primary_healthy:
                # Whole-run downgrade: use fallback directly, skip primary.
                try:
                    await self._fallback.produce_clip(  # type: ignore[union-attr]
                        scene=scene,
                        target_duration_s=target,
                        width=width,
                        height=height,
                        fps=_FPS,
                        dest=dest,
                    )
                    counts["fallback"] += 1
                except SceneSourceError as exc:
                    raise MediaError(
                        f"fallback failed on scene {scene['index']} (primary already skipped): {exc}"
                    ) from exc
                prepared_paths.append(dest)
                continue

            # ... existing primary→fallback try/except block unchanged ...
```

Finally, include `primary_healthy` in the returned metadata:

```python
        return StageResult(
            artifacts={"video_silent.mp4": dest_video},
            metadata={
                "clip_count": len(prepared_paths),
                "source_counts": counts,
                "primary_healthy": primary_healthy,
            },
        )
```

- [ ] **Step 4: Run all media-agent tests**

Run: `uv run pytest tests/unit/test_media_agent.py -v`
Expected: all PASS, including the new healthcheck tests and the existing ones (which pass `primary_healthcheck=None`, the default).

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/agents/media.py tests/unit/test_media_agent.py
git commit -m "media: skip primary entirely when startup healthcheck fails"
```

---

## Task 10: Wire CLI

**Files:**
- Modify: `src/yt_auto/cli.py`
- Modify: `tests/unit/test_cli.py` (if it exercises build_media_agent — otherwise smoke-test manually)

The current `build_media_agent` constructs a `MediaAgent(pexels=...)` with the old signature. After Task 8 that signature no longer exists, so the CLI doesn't import cleanly until this task lands. Combine task 8 and 9 into a single working state before pushing.

- [ ] **Step 1: Inspect existing CLI build function and tests**

Run:
```bash
grep -n "build_media_agent\|MediaAgent" src/yt_auto/cli.py tests/unit/test_cli.py
```

Decide whether tests need updating. If `test_cli.py` only checks parser behavior (not agent assembly), it's untouched.

- [ ] **Step 2: Update `build_media_agent`**

In `src/yt_auto/cli.py`, change the imports near the top:

```python
from yt_auto.agents.media import MediaAgent
from yt_auto.agents.sources import LocalDiffusionSource, PexelsSource
from yt_auto.clients.comfyui import ComfyUIClient
from yt_auto.clients.pexels import PexelsClient
```

Replace `build_media_agent`:

```python
def build_media_agent(settings: Settings) -> MediaAgent:
    pexels_client = PexelsClient(api_key=settings.pexels_api_key)
    pexels_source = PexelsSource(pexels=pexels_client, per_page=settings.pexels_per_page)

    if settings.media_source == "pexels":
        return MediaAgent(primary=pexels_source, fallback=None)

    # local_diffusion: primary = ComfyUI, fallback = Pexels.
    # video_style comes from script.json which is read inside MediaAgent.run, so we
    # pass a *factory* — MediaAgent calls it with the resolved video_style at run time.
    comfy_client = ComfyUIClient(base_url=settings.comfyui_url)

    def local_source_factory(video_style: str) -> LocalDiffusionSource:
        return LocalDiffusionSource(comfyui=comfy_client, video_style=video_style)

    return MediaAgent(
        primary=local_source_factory,
        fallback=pexels_source,
        primary_healthcheck=comfy_client.ping,
    )
```

The factory pattern: `LocalDiffusionSource` needs `video_style` from `script.json`, but the agent is constructed before `script.json` exists. `MediaAgent` already accepts `SceneSource | Callable[[str], SceneSource]` for `primary` (Task 8 set this up) — passing a factory means the agent calls it once per run with `script["video_style"]`.

Add a test for the factory invocation in `tests/unit/test_media_agent.py`:

```python
@pytest.mark.asyncio
async def test_media_agent_calls_primary_factory_with_video_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received_styles: list[str] = []

    def factory(video_style: str) -> _RecordingSource:
        received_styles.append(video_style)
        return _RecordingSource()

    async def fake_concat(**kwargs: Any) -> None:
        kwargs["dest"].write_bytes(b"VIDEO")

    monkeypatch.setattr("yt_auto.agents.media.concat_clips", fake_concat)

    agent = MediaAgent(primary=factory, fallback=None)
    await agent.run(_make_ctx(tmp_path, video_style="oil painting, romanticist"))
    assert received_styles == ["oil painting, romanticist"]
```

- [ ] **Step 3: Run all unit tests**

Run: `uv run pytest tests/unit -v`
Expected: all PASS.

- [ ] **Step 4: Smoke-test the CLI imports**

Run:
```bash
uv run python -c "from yt_auto.cli import build_media_agent; from yt_auto.config import get_settings; print(build_media_agent(get_settings()))"
```
Expected: prints a `MediaAgent` instance, no errors.

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/cli.py src/yt_auto/agents/media.py tests/unit/test_media_agent.py
git commit -m "cli: wire LocalDiffusionSource with Pexels fallback"
```

---

## Task 11: .gitignore + setup docs

**Files:**
- Modify: `.gitignore`
- Create: `docs/comfyui-setup.md`

- [ ] **Step 1: Update .gitignore**

Append to `.gitignore`:

```
# Bundled ComfyUI install (not source-controlled)
third_party/
```

- [ ] **Step 2: Write the setup doc**

Create `docs/comfyui-setup.md`:

```markdown
# ComfyUI setup (local SDXL b-roll)

The Media Agent's `local_diffusion` source talks to a ComfyUI server you run
locally. This doc covers the one-time install and how to start the server.

## Prerequisites

- NVIDIA GPU with ≥10 GB VRAM (tested on RTX 5070 12 GB)
- Recent NVIDIA driver supporting CUDA 12.x
- Python 3.10–3.12 available for ComfyUI's own venv (separate from this project)

## Install

From the project root:

```bash
mkdir -p third_party
git clone https://github.com/comfyanonymous/ComfyUI third_party/ComfyUI
cd third_party/ComfyUI
python -m venv .venv
. .venv/Scripts/activate   # Windows; use .venv/bin/activate on Linux/macOS
pip install --upgrade pip
pip install -r requirements.txt
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

(Adjust the torch CUDA wheel index if your driver needs a different version.)

## Download SDXL base 1.0

Roughly 7 GB.

```bash
mkdir -p models/checkpoints
curl -L https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors \
  -o models/checkpoints/sd_xl_base_1.0.safetensors
```

(If you have HuggingFace auth set up you may need `huggingface-cli download` instead.)

## Run

From `third_party/ComfyUI` with the venv active:

```bash
python main.py --listen 127.0.0.1 --port 8188
```

Leave that terminal running. The pipeline talks to it at `http://127.0.0.1:8188`.

Smoke test from a separate terminal:

```bash
curl http://127.0.0.1:8188/system_stats
```

You should see a JSON system info blob.

## Pipeline config

Defaults in `src/yt_auto/config.py` already point at `http://127.0.0.1:8188` and
set `media_source=local_diffusion`. Override either via environment:

```bash
export COMFYUI_URL=http://127.0.0.1:8189   # if you moved the port
export MEDIA_SOURCE=pexels                 # to force the Pexels fallback
```

## Failure modes

- **ComfyUI not running:** the run logs one warning at startup, then falls back
  to Pexels for the whole run. The video still renders.
- **Per-scene generation timeout / crash:** that one scene falls back to Pexels;
  the rest stay on SDXL.
- **Pexels also fails on the same scene:** the run aborts with `MediaError`.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore docs/comfyui-setup.md
git commit -m "docs: add ComfyUI setup guide; gitignore third_party"
```

---

## Task 12: End-to-end manual verification

This is not a test — it's a smoke-check before declaring the feature done.

- [ ] **Step 1: Install ComfyUI per `docs/comfyui-setup.md` and start it.**

- [ ] **Step 2: Run a short-format pipeline end-to-end.**

```bash
uv run python -m yt_auto pipeline-full "the strangler fig and the host tree" --format short
```

- [ ] **Step 3: Check the output.**

- Open the resulting `final.mp4` from `outputs/`.
- Confirm the b-roll matches the narration topic-by-scene (not generic stock).
- Confirm scenes share a coherent visual style.
- Confirm motion is present (slow zoom/pan, not static).
- Check logs for any `primary_source_failed` warnings — a few are OK, lots means a prompt or model problem worth investigating.

- [ ] **Step 4: Smoke-test the fallback.**

Stop ComfyUI. Re-run the pipeline. Confirm:
- Log line shows `comfyui_unreachable` or equivalent warning.
- Video still renders, this time with Pexels footage.
- `result.metadata["source_counts"]` shows `primary=0, fallback=N`.

- [ ] **Step 5: Commit any tweaks you needed during smoke-test.**

If you found a bug, fix it, add a regression test, commit.

---

## Out of scope (per spec §11)

- SVD / AnimateDiff
- Flux model support
- LoRA loading or style training
- Upscaling (Real-ESRGAN etc.)
- Face / character consistency
- Automatic ComfyUI process management
- Per-run media-source CLI flag (env var override is sufficient for now)
- GPU memory monitoring
