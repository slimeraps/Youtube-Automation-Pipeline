# Phase 1 — Skeleton + Script Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the project skeleton and build the Script Agent — a CLI command that takes a topic and writes a fully-formed `script.json` (narration + scene-by-scene visual prompts + YouTube metadata + reproducible random-parameter trail) for use by later agents.

**Architecture:** Single-package `src/yt_auto/` layout. The Script Agent makes two Gemini calls (narration first, then scene visuals) with a local scene-timing pass between them. A seeded parameter-pool system makes the same topic produce a different video every run. No FastAPI, no DB, no executor yet — the agent is exercised standalone through a CLI.

**Tech Stack:** Python 3.12, uv, ruff, mypy, pytest + pytest-asyncio, pydantic-settings, structlog, jinja2, httpx, google-genai.

**Spec reference:** [docs/superpowers/specs/2026-05-30-youtube-automation-pipeline-design.md](../specs/2026-05-30-youtube-automation-pipeline-design.md) §6 (Script Agent) and §14 (Phase 1 boundary).

---

## Task 1 — Project bootstrap (pyproject, deps, tool config)

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/yt_auto/__init__.py`
- Create: `src/yt_auto/__main__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Verify uv is installed**

Run: `uv --version`
Expected: prints a version like `uv 0.4.x`. If missing, install per https://docs.astral.sh/uv/.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "yt-auto"
version = "0.1.0"
description = "YouTube automation pipeline"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.4",
    "structlog>=24.1",
    "jinja2>=3.1",
    "httpx>=0.27",
    "google-genai>=0.3",
    "python-ulid>=2.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/yt_auto"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src/yt_auto"]

[[tool.mypy.overrides]]
module = "google.genai.*"
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: marks tests that hit real external APIs (deselect with -m 'not integration')",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: Create package `__init__.py` files**

`src/yt_auto/__init__.py`:
```python
"""YouTube automation pipeline."""

__version__ = "0.1.0"
```

`src/yt_auto/__main__.py`:
```python
"""Entrypoint so `python -m yt_auto` works."""
from yt_auto.cli import main

if __name__ == "__main__":
    main()
```

`tests/__init__.py`: empty file.

- [ ] **Step 4: Create README.md**

```markdown
# YouTube Automation Pipeline

Generates a complete narrated video from a single topic string. See
[the design doc](docs/superpowers/specs/2026-05-30-youtube-automation-pipeline-design.md)
for the full architecture.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
# fill in API keys in .env
```

## Phase 1 usage

```bash
uv run python -m yt_auto script "the history of espresso" --format short
```

Writes `outputs/<run_id>/script.json`.

## Tests

```bash
uv run pytest                      # unit tests only (fast)
uv run pytest -m integration       # live API tests (costs a few cents)
```
```

- [ ] **Step 5: Sync deps and confirm the package imports**

Run: `uv sync --extra dev`
Expected: creates `.venv/`, installs all deps, no errors.

Run: `uv run python -c "import yt_auto; print(yt_auto.__version__)"`
Expected: prints `0.1.0`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md src/yt_auto/__init__.py src/yt_auto/__main__.py tests/__init__.py
git commit -m "Bootstrap project: pyproject, package skeleton, README"
```

---

## Task 2 — Settings (`config.py`)

**Files:**
- Create: `.env.example`
- Create: `src/yt_auto/config.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Create `.env.example` (Phase 1 keys only)**

```
# --- LLM ---
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- App ---
DATA_DIR=./data
OUTPUTS_DIR=./outputs
LOG_LEVEL=INFO
```

- [ ] **Step 2: Write the failing test**

`tests/unit/__init__.py`: empty file.

`tests/unit/test_config.py`:
```python
from pathlib import Path

import pytest

from yt_auto.config import Settings


def test_settings_loads_required_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("OUTPUTS_DIR", "./outputs")
    monkeypatch.setenv("DATA_DIR", "./data")

    settings = Settings()

    assert settings.gemini_api_key == "fake-key"
    assert settings.gemini_model == "gemini-2.5-flash"  # default
    assert settings.outputs_dir == Path("./outputs")
    assert settings.log_level == "INFO"


def test_settings_missing_required_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.config'`.

- [ ] **Step 4: Implement `config.py`**

`src/yt_auto/config.py`:
```python
"""Application settings loaded from environment / .env file."""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # App
    data_dir: Path = Field(default=Path("./data"))
    outputs_dir: Path = Field(default=Path("./outputs"))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add .env.example src/yt_auto/config.py tests/unit/__init__.py tests/unit/test_config.py
git commit -m "Add Settings loaded from .env via pydantic-settings"
```

---

## Task 3 — Logging (`logging.py`)

**Files:**
- Create: `src/yt_auto/logging.py`
- Create: `tests/unit/test_logging.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_logging.py`:
```python
import structlog

from yt_auto.logging import configure_logging, get_logger


def test_get_logger_returns_structlog_bound_logger() -> None:
    configure_logging(level="INFO")
    log = get_logger("test")
    assert isinstance(log, structlog.stdlib.BoundLogger) or hasattr(log, "info")


def test_configure_logging_is_idempotent() -> None:
    configure_logging(level="INFO")
    configure_logging(level="DEBUG")
    log = get_logger("test")
    log.info("hello", x=1)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.logging'`.

- [ ] **Step 3: Implement `logging.py`**

`src/yt_auto/logging.py`:
```python
"""structlog setup. Call configure_logging() once at process start."""
import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level),
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> Any:
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_logging.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_auto/logging.py tests/unit/test_logging.py
git commit -m "Add structlog setup with idempotent configure_logging"
```

---

## Task 4 — Pipeline contracts (`pipeline/base.py`, `pipeline/context.py`)

**Files:**
- Create: `src/yt_auto/pipeline/__init__.py`
- Create: `src/yt_auto/pipeline/base.py`
- Create: `src/yt_auto/pipeline/context.py`
- Create: `tests/unit/test_pipeline_context.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_pipeline_context.py`:
```python
from pathlib import Path

from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext


def test_run_context_merge_combines_artifacts_and_metadata(tmp_path: Path) -> None:
    ctx = RunContext(
        run_id="01HZZ",
        topic="t",
        format="long",
        visibility="public",
        run_dir=tmp_path,
        artifacts={},
        metadata={"a": 1},
    )
    result = StageResult(
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={"b": 2},
    )

    merged = ctx.merge(result)

    assert merged.artifacts == {"script.json": tmp_path / "script.json"}
    assert merged.metadata == {"a": 1, "b": 2}
    assert merged.run_id == "01HZZ"
    # original ctx untouched
    assert ctx.artifacts == {}
    assert ctx.metadata == {"a": 1}


def test_run_context_merge_later_metadata_wins() -> None:
    ctx = RunContext(
        run_id="01HZZ",
        topic="t",
        format="short",
        visibility="private",
        run_dir=Path("/tmp"),
        artifacts={},
        metadata={"k": "old"},
    )
    result = StageResult(artifacts={}, metadata={"k": "new"})

    merged = ctx.merge(result)

    assert merged.metadata["k"] == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pipeline_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.pipeline'`.

- [ ] **Step 3: Implement `pipeline/__init__.py`**

`src/yt_auto/pipeline/__init__.py`: empty file.

- [ ] **Step 4: Implement `pipeline/base.py`**

`src/yt_auto/pipeline/base.py`:
```python
"""Agent protocol and StageResult — the shared contract for every pipeline stage."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class StageResult:
    """What an agent returns when it finishes successfully."""
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    """Every pipeline stage implements this."""
    name: str

    async def run(self, ctx: "RunContext") -> StageResult: ...


# Late import to avoid circularity
from yt_auto.pipeline.context import RunContext  # noqa: E402
```

- [ ] **Step 5: Implement `pipeline/context.py`**

`src/yt_auto/pipeline/context.py`:
```python
"""RunContext: the read-mostly state object threaded through every stage."""
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

VideoFormat = Literal["long", "short"]
Visibility = Literal["public", "unlisted", "private"]


@dataclass
class RunContext:
    run_id: str
    topic: str
    format: VideoFormat
    visibility: Visibility
    run_dir: Path
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def merge(self, result: "StageResult") -> "RunContext":
        """Return a new RunContext with this stage's outputs folded in."""
        return replace(
            self,
            artifacts={**self.artifacts, **result.artifacts},
            metadata={**self.metadata, **result.metadata},
        )


# Late import to avoid circularity
from yt_auto.pipeline.base import StageResult  # noqa: E402
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_pipeline_context.py -v`
Expected: both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/yt_auto/pipeline tests/unit/test_pipeline_context.py
git commit -m "Add Agent protocol, StageResult, and RunContext with merge()"
```

---

## Task 5 — Prompt parameter pools (`prompts/script_meta.py`)

**Files:**
- Create: `src/yt_auto/prompts/__init__.py`
- Create: `src/yt_auto/prompts/script_meta.py`
- Create: `tests/unit/test_script_meta.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_script_meta.py`:
```python
from collections import Counter

import pytest

from yt_auto.prompts.script_meta import (
    HOOK_STYLES,
    NARRATIVE_STYLES,
    STRUCTURES,
    TONES,
    VOICE_CATEGORIES,
    PromptParams,
    build_params,
    target_duration_seconds,
    target_word_count,
)


def test_build_params_is_deterministic_for_same_seed() -> None:
    a = build_params(topic="x", video_format="long", seed=42)
    b = build_params(topic="x", video_format="long", seed=42)
    assert a == b


def test_build_params_returns_values_from_pools() -> None:
    p = build_params(topic="x", video_format="long", seed=1)
    assert p.tone in TONES
    assert p.structure in STRUCTURES
    assert p.narrative_style in NARRATIVE_STYLES
    assert p.hook_style in HOOK_STYLES
    assert p.voice_category in VOICE_CATEGORIES


def test_build_params_with_no_seed_generates_random_seed() -> None:
    p = build_params(topic="x", video_format="long", seed=None)
    assert isinstance(p.seed, int)
    assert p.seed >= 0


def test_all_pool_options_are_reachable_across_many_seeds() -> None:
    tones_seen: set[str] = set()
    structures_seen: set[str] = set()
    for seed in range(500):
        p = build_params(topic="x", video_format="long", seed=seed)
        tones_seen.add(p.tone)
        structures_seen.add(p.structure)
    assert tones_seen == set(TONES)
    assert structures_seen == set(STRUCTURES)


def test_ominous_tone_biases_toward_deep_or_mysterious_voice() -> None:
    voice_counts: Counter[str] = Counter()
    for seed in range(2000):
        p = build_params(topic="x", video_format="long", seed=seed)
        if p.tone == "ominous":
            voice_counts[p.voice_category] += 1

    total = sum(voice_counts.values())
    assert total > 0, "ominous tone should appear in 2000 seeds"
    matching = voice_counts["deep_documentary"] + voice_counts["mysterious_lowkey"]
    assert matching / total >= 0.55, f"expected >=55%, got {matching/total:.0%}"


@pytest.mark.parametrize(
    "fmt,expected",
    [("long", 600), ("short", 50)],
)
def test_target_duration_seconds(fmt: str, expected: int) -> None:
    assert target_duration_seconds(fmt) == expected  # type: ignore[arg-type]


def test_target_word_count_uses_default_wps() -> None:
    # 600s * 2.4 wps = 1440
    assert target_word_count("long") == 1440
    # 50s * 2.4 wps = 120
    assert target_word_count("short") == 120


def test_prompt_params_to_dict_round_trip() -> None:
    p = build_params(topic="x", video_format="long", seed=7)
    d = p.to_dict()
    assert d["tone"] == p.tone
    assert d["seed"] == p.seed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_script_meta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.prompts'`.

- [ ] **Step 3: Implement `prompts/__init__.py`**

`src/yt_auto/prompts/__init__.py`: empty file.

- [ ] **Step 4: Implement `prompts/script_meta.py`**

`src/yt_auto/prompts/script_meta.py`:
```python
"""Pools of story-shape parameters + the seeded picker used by the Script Agent.

Same topic, same seed → same parameter choices → reproducible run.
Same topic, different seed → different video.
"""
import random
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Literal

VideoFormat = Literal["long", "short"]

TONES: tuple[str, ...] = (
    "contemplative",
    "urgent",
    "playful",
    "ominous",
    "wonder-struck",
    "deadpan",
    "warm-mentor",
    "investigative",
)

STRUCTURES: tuple[str, ...] = (
    "three_act",
    "list_countdown",
    "chronological_journey",
    "question_then_answer",
    "myth_vs_reality",
    "zoom_in_zoom_out",
)

NARRATIVE_STYLES: tuple[str, ...] = (
    "second_person_immersive",
    "third_person_omniscient",
    "first_person_observer",
    "documentary_clinical",
    "campfire_storyteller",
)

HOOK_STYLES: tuple[str, ...] = (
    "cold_open_question",
    "shocking_statistic",
    "in_medias_res_scene",
    "contrarian_claim",
    "paradox",
)

VOICE_CATEGORIES: tuple[str, ...] = (
    "calm_narrator",
    "energetic_explainer",
    "deep_documentary",
    "warm_storyteller",
    "mysterious_lowkey",
)

# tone -> (preferred voices, weight bias for preferred).
# Anything not in preferred is picked uniformly from the rest.
_TONE_VOICE_BIAS: dict[str, tuple[tuple[str, ...], float]] = {
    "ominous": (("deep_documentary", "mysterious_lowkey"), 0.7),
    "urgent": (("energetic_explainer", "deep_documentary"), 0.65),
    "playful": (("energetic_explainer", "warm_storyteller"), 0.65),
    "contemplative": (("calm_narrator", "warm_storyteller"), 0.65),
    "wonder-struck": (("warm_storyteller", "calm_narrator"), 0.6),
    "deadpan": (("calm_narrator", "mysterious_lowkey"), 0.6),
    "warm-mentor": (("warm_storyteller", "calm_narrator"), 0.7),
    "investigative": (("deep_documentary", "mysterious_lowkey"), 0.65),
}

# Words-per-second target by voice category (used for length math).
_WPS_BY_CATEGORY: dict[str, float] = {
    "calm_narrator": 2.3,
    "energetic_explainer": 2.7,
    "deep_documentary": 2.2,
    "warm_storyteller": 2.4,
    "mysterious_lowkey": 2.1,
}

DEFAULT_WPS = 2.4

_DURATION_BY_FORMAT: dict[VideoFormat, int] = {"long": 600, "short": 50}


@dataclass(frozen=True)
class PromptParams:
    tone: str
    structure: str
    narrative_style: str
    hook_style: str
    voice_category: str
    seed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pick_voice_for_tone(rng: random.Random, tone: str) -> str:
    bias = _TONE_VOICE_BIAS.get(tone)
    if bias is None:
        return rng.choice(VOICE_CATEGORIES)
    preferred, weight = bias
    if rng.random() < weight:
        return rng.choice(preferred)
    rest = tuple(v for v in VOICE_CATEGORIES if v not in preferred)
    return rng.choice(rest)


def build_params(topic: str, video_format: VideoFormat, seed: int | None) -> PromptParams:
    """Pick a tone/structure/etc. tuple. Determined entirely by seed if provided."""
    if seed is None:
        seed = secrets.randbits(63)
    rng = random.Random(seed)
    tone = rng.choice(TONES)
    return PromptParams(
        tone=tone,
        structure=rng.choice(STRUCTURES),
        narrative_style=rng.choice(NARRATIVE_STYLES),
        hook_style=rng.choice(HOOK_STYLES),
        voice_category=_pick_voice_for_tone(rng, tone),
        seed=seed,
    )


def target_duration_seconds(video_format: VideoFormat) -> int:
    return _DURATION_BY_FORMAT[video_format]


def wps_for_voice(voice_category: str) -> float:
    return _WPS_BY_CATEGORY.get(voice_category, DEFAULT_WPS)


def target_word_count(video_format: VideoFormat, voice_category: str | None = None) -> int:
    wps = wps_for_voice(voice_category) if voice_category else DEFAULT_WPS
    return int(target_duration_seconds(video_format) * wps)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_script_meta.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/prompts/__init__.py src/yt_auto/prompts/script_meta.py tests/unit/test_script_meta.py
git commit -m "Add seeded prompt parameter pools and tone-weighted voice selection"
```

---

## Task 6 — Jinja meta-prompt templates

**Files:**
- Create: `src/yt_auto/prompts/templates/narration.j2`
- Create: `src/yt_auto/prompts/templates/scene_visuals.j2`
- Create: `src/yt_auto/prompts/templates/__init__.py`
- Modify: `src/yt_auto/prompts/script_meta.py` (add `render_narration_prompt` and `render_scene_visuals_prompt`)
- Create: `tests/unit/test_prompt_templates.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_prompt_templates.py`:
```python
from yt_auto.prompts.script_meta import (
    build_params,
    render_narration_prompt,
    render_scene_visuals_prompt,
    target_word_count,
)


def test_render_narration_prompt_includes_all_params() -> None:
    params = build_params(topic="the history of espresso", video_format="short", seed=1)
    prompt = render_narration_prompt(
        topic="the history of espresso",
        video_format="short",
        params=params,
        word_target=target_word_count("short", params.voice_category),
    )

    assert "the history of espresso" in prompt
    assert params.tone in prompt
    assert params.structure in prompt
    assert params.narrative_style in prompt
    assert params.hook_style in prompt
    assert "JSON" in prompt
    assert "narration" in prompt
    assert "scene_breaks" in prompt
    assert "youtube" in prompt
    # Word target must appear so the model sees it
    assert str(target_word_count("short", params.voice_category)) in prompt


def test_render_scene_visuals_prompt_serializes_scene_list() -> None:
    scenes = [
        {"index": 0, "narration_excerpt": "a curious traveler arrives"},
        {"index": 1, "narration_excerpt": "the city wakes at dawn"},
    ]
    prompt = render_scene_visuals_prompt(scenes=scenes)

    assert "a curious traveler arrives" in prompt
    assert "the city wakes at dawn" in prompt
    assert "visual_prompt" in prompt
    assert "pexels_query" in prompt
    assert "JSON" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompt_templates.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_narration_prompt'`.

- [ ] **Step 3: Create the templates directory marker**

`src/yt_auto/prompts/templates/__init__.py`: empty file (so templates are packaged).

- [ ] **Step 4: Create `narration.j2`**

`src/yt_auto/prompts/templates/narration.j2`:
```jinja
You are a YouTube narration scriptwriter.

TOPIC: {{ topic }}
FORMAT: {{ video_format }} ({{ word_target }} words target, ±10% acceptable)

STORY DIRECTION (use these to shape the script):
- Tone: {{ params.tone }}
- Structure: {{ params.structure }}
- Narrative style: {{ params.narrative_style }}
- Hook style: {{ params.hook_style }}

INSTRUCTIONS:
1. Open with a hook matching the chosen hook style.
2. Develop the topic using the chosen structure.
3. Maintain the chosen tone and narrative style throughout.
4. Aim for {{ word_target }} words of narration total.
5. Break the narration into 8-30 distinct visual scenes. A scene break is
   wherever the visual subject on screen would naturally change.
6. Also produce YouTube metadata: a clickable title (<=70 chars),
   a 2-3 paragraph description, and 8-15 lowercase tags.

OUTPUT FORMAT: a single JSON object, no prose around it, matching:
{
  "narration": "<the full narration as one string>",
  "scene_breaks": [
    {"index": 0, "narration_excerpt": "<the sentences spoken during scene 0>"},
    {"index": 1, "narration_excerpt": "<...>"}
  ],
  "youtube": {
    "title": "<title>",
    "description": "<description>",
    "tags": ["tag1", "tag2"]
  }
}

The concatenation of every narration_excerpt MUST equal the full narration
exactly (same words, same order, no overlap, no gaps).
```

- [ ] **Step 5: Create `scene_visuals.j2`**

`src/yt_auto/prompts/templates/scene_visuals.j2`:
```jinja
You are a visual director for a narrated video. For each scene below, write:
- visual_prompt: a vivid, concrete description of what should appear on screen (1-2 sentences)
- pexels_query: 3-6 keywords suitable for searching Pexels stock footage

SCENES:
{% for scene in scenes %}
- Scene {{ scene.index }}: {{ scene.narration_excerpt }}
{% endfor %}

OUTPUT FORMAT: a single JSON object, no prose around it, matching:
{
  "scenes": [
    {"index": 0, "visual_prompt": "<...>", "pexels_query": "<...>"},
    {"index": 1, "visual_prompt": "<...>", "pexels_query": "<...>"}
  ]
}

Return exactly one entry per input scene, in the same order, with matching indexes.
```

- [ ] **Step 6: Add render functions to `script_meta.py`**

Append to `src/yt_auto/prompts/script_meta.py`:
```python
from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(
    loader=PackageLoader("yt_auto.prompts", "templates"),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_narration_prompt(
    topic: str,
    video_format: VideoFormat,
    params: PromptParams,
    word_target: int,
) -> str:
    tmpl = _env.get_template("narration.j2")
    return tmpl.render(
        topic=topic,
        video_format=video_format,
        params=params,
        word_target=word_target,
    )


def render_scene_visuals_prompt(scenes: list[dict[str, Any]]) -> str:
    tmpl = _env.get_template("scene_visuals.j2")
    return tmpl.render(scenes=scenes)
```

- [ ] **Step 7: Ensure templates are packaged**

Add to `pyproject.toml` under `[tool.hatch.build.targets.wheel]`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/yt_auto"]

[tool.hatch.build.targets.wheel.force-include]
"src/yt_auto/prompts/templates" = "yt_auto/prompts/templates"
```

(Replace the existing `[tool.hatch.build.targets.wheel]` block with the two blocks above.)

- [ ] **Step 8: Re-sync so editable install picks up template files**

Run: `uv sync --extra dev`
Expected: no errors.

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_prompt_templates.py -v`
Expected: both tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/yt_auto/prompts/templates src/yt_auto/prompts/script_meta.py pyproject.toml tests/unit/test_prompt_templates.py
git commit -m "Add Jinja meta-prompt templates for narration and scene visuals"
```

---

## Task 7 — Gemini client (`clients/gemini.py`)

The client is a thin async wrapper that returns a parsed dict from a JSON-mode Gemini call. It handles:
- **Transport-level retries** for 429/5xx with exponential backoff.
- **JSON-parse retries** when the model occasionally returns malformed JSON despite JSON mode (spec §6: "Retry up to 2 times with same prompt").

It does NOT handle content-level retries (wrong word count, missing fields) — those belong to the agent because the corrective follow-up is content-aware.

**Files:**
- Create: `src/yt_auto/clients/__init__.py`
- Create: `src/yt_auto/clients/gemini.py`
- Create: `tests/unit/test_gemini_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_gemini_client.py`:
```python
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from yt_auto.clients.gemini import (
    GeminiClient,
    GeminiInvalidJSONError,
    GeminiTransportError,
)


@dataclass
class _FakeResponse:
    text: str


class _FakeAsyncModels:
    """Minimal stand-in for `genai.Client().aio.models`."""

    def __init__(self, handler: Callable[[str], Awaitable[_FakeResponse]]) -> None:
        self._handler = handler
        self.calls: list[dict[str, object]] = []

    async def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return await self._handler(contents)


class _FakeAio:
    def __init__(self, models: _FakeAsyncModels) -> None:
        self.models = models


class _FakeGenaiClient:
    def __init__(self, models: _FakeAsyncModels) -> None:
        self.aio = _FakeAio(models)


async def _ok_with(text: str) -> Callable[[str], Awaitable[_FakeResponse]]:
    async def _handler(_prompt: str) -> _FakeResponse:
        return _FakeResponse(text=text)
    return _handler


@pytest.mark.asyncio
async def test_generate_json_parses_valid_response() -> None:
    handler = await _ok_with(json.dumps({"hello": "world"}))
    models = _FakeAsyncModels(handler)
    client = GeminiClient(api_key="k", model="m", _genai_client=_FakeGenaiClient(models))

    result = await client.generate_json("prompt")

    assert result == {"hello": "world"}
    assert models.calls[0]["model"] == "m"
    assert models.calls[0]["contents"] == "prompt"


@pytest.mark.asyncio
async def test_generate_json_retries_on_invalid_json_then_succeeds() -> None:
    attempts = {"n": 0}

    async def handler(_prompt: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return _FakeResponse(text="not json {{{")
        return _FakeResponse(text=json.dumps({"ok": True}))

    client = GeminiClient(
        api_key="k",
        model="m",
        max_json_retries=2,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    result = await client.generate_json("prompt")
    assert result == {"ok": True}
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_generate_json_gives_up_after_max_json_retries() -> None:
    async def handler(_prompt: str) -> _FakeResponse:
        return _FakeResponse(text="still not json")

    client = GeminiClient(
        api_key="k",
        model="m",
        max_json_retries=2,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    with pytest.raises(GeminiInvalidJSONError):
        await client.generate_json("prompt")


@pytest.mark.asyncio
async def test_generate_json_retries_on_transport_error_then_succeeds() -> None:
    attempts = {"n": 0}

    async def handler(_prompt: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("simulated 429")
        return _FakeResponse(text=json.dumps({"ok": True}))

    client = GeminiClient(
        api_key="k",
        model="m",
        max_transport_retries=3,
        initial_backoff_s=0,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    result = await client.generate_json("prompt")
    assert result == {"ok": True}
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_generate_json_gives_up_after_max_retries() -> None:
    async def handler(_prompt: str) -> _FakeResponse:
        raise RuntimeError("always fails")

    client = GeminiClient(
        api_key="k",
        model="m",
        max_transport_retries=2,
        initial_backoff_s=0,
        _genai_client=_FakeGenaiClient(_FakeAsyncModels(handler)),
    )

    with pytest.raises(GeminiTransportError):
        await client.generate_json("prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_gemini_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.clients'`.

- [ ] **Step 3: Implement `clients/__init__.py`**

`src/yt_auto/clients/__init__.py`: empty file.

- [ ] **Step 4: Implement `clients/gemini.py`**

`src/yt_auto/clients/gemini.py`:
```python
"""Thin async wrapper around google-genai for JSON-mode calls."""
import asyncio
import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from yt_auto.logging import get_logger

log = get_logger(__name__)


class GeminiError(Exception):
    """Base for all Gemini client errors."""


class GeminiTransportError(GeminiError):
    """Network / 429 / 5xx after retries exhausted."""


class GeminiInvalidJSONError(GeminiError):
    """The model returned content that isn't valid JSON."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class GeminiClient:
    """Async JSON-mode Gemini client with transport-level retries."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_transport_retries: int = 3,
        max_json_retries: int = 2,
        initial_backoff_s: float = 1.0,
        _genai_client: Any = None,
    ) -> None:
        self._model = model
        self._max_transport_retries = max_transport_retries
        self._max_json_retries = max_json_retries
        self._initial_backoff = initial_backoff_s
        self._client = _genai_client or genai.Client(api_key=api_key)

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        """Send `prompt`, expect JSON, return parsed dict.

        Retries malformed JSON up to `max_json_retries` times with the same prompt
        (gemini occasionally drops braces despite JSON mode).
        """
        config = genai_types.GenerateContentConfig(response_mime_type="application/json")
        last_raw = ""
        last_exc: json.JSONDecodeError | None = None
        for attempt in range(1, self._max_json_retries + 2):  # initial + retries
            text = await self._call_with_retries(prompt=prompt, config=config)
            try:
                return json.loads(text)  # type: ignore[no-any-return]
            except json.JSONDecodeError as e:
                last_raw = text
                last_exc = e
                log.warning(
                    "gemini_invalid_json",
                    attempt=attempt,
                    max_attempts=self._max_json_retries + 1,
                    snippet=text[:120],
                )
        raise GeminiInvalidJSONError(
            f"model returned non-JSON after {self._max_json_retries} retries: {last_exc}",
            raw_text=last_raw,
        )

    async def _call_with_retries(self, *, prompt: str, config: Any) -> str:
        backoff = self._initial_backoff
        last_exc: Exception | None = None
        for attempt in range(1, self._max_transport_retries + 1):
            try:
                resp = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )
                return resp.text  # type: ignore[no-any-return]
            except Exception as e:  # noqa: BLE001
                last_exc = e
                log.warning(
                    "gemini_transport_error",
                    attempt=attempt,
                    max_attempts=self._max_transport_retries,
                    error=str(e),
                )
                if attempt >= self._max_transport_retries:
                    break
                if backoff > 0:
                    await asyncio.sleep(backoff)
                backoff *= 4
        raise GeminiTransportError(
            f"gemini call failed after {self._max_transport_retries} attempts: {last_exc}"
        ) from last_exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_gemini_client.py -v`
Expected: all four tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/clients tests/unit/test_gemini_client.py
git commit -m "Add async Gemini JSON client with transport + JSON-parse retries"
```

---

## Task 8 — Script Agent (`agents/script.py`)

This is the centerpiece. Two Gemini calls + a local timing pass + length-retry logic + writes `script.json`.

**Files:**
- Create: `src/yt_auto/agents/__init__.py`
- Create: `src/yt_auto/agents/script.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/gemini_narration_response.json`
- Create: `tests/fixtures/gemini_scene_visuals_response.json`
- Create: `tests/unit/test_script_agent.py`

- [ ] **Step 1: Create fixture files**

`tests/fixtures/gemini_narration_response.json`:
```json
{
  "narration": "A curious traveler arrives at dawn. The city wakes slowly. Steam rises from copper pots. The first cup is poured.",
  "scene_breaks": [
    {"index": 0, "narration_excerpt": "A curious traveler arrives at dawn."},
    {"index": 1, "narration_excerpt": "The city wakes slowly."},
    {"index": 2, "narration_excerpt": "Steam rises from copper pots."},
    {"index": 3, "narration_excerpt": "The first cup is poured."}
  ],
  "youtube": {
    "title": "Espresso at Dawn",
    "description": "A short journey through the origins of espresso.",
    "tags": ["espresso", "coffee", "history"]
  }
}
```

`tests/fixtures/gemini_scene_visuals_response.json`:
```json
{
  "scenes": [
    {"index": 0, "visual_prompt": "lone figure approaches old city gates at sunrise", "pexels_query": "traveler city gates sunrise"},
    {"index": 1, "visual_prompt": "narrow cobblestone streets coming alive with morning light", "pexels_query": "cobblestone street morning"},
    {"index": 2, "visual_prompt": "close-up of polished copper espresso pots venting steam", "pexels_query": "copper espresso steam closeup"},
    {"index": 3, "visual_prompt": "barista pours rich crema into a small white cup", "pexels_query": "barista pouring espresso crema"}
  ]
}
```

- [ ] **Step 2: Create `tests/conftest.py`**

`tests/conftest.py`:
```python
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def narration_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "gemini_narration_response.json").read_text())


@pytest.fixture
def scene_visuals_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "gemini_scene_visuals_response.json").read_text())
```

- [ ] **Step 3: Write the failing tests**

`tests/unit/test_script_agent.py`:
```python
import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.script import ScriptAgent
from yt_auto.pipeline.context import RunContext


class FakeGemini:
    """Returns queued responses; raises if out of responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError(f"Unexpected extra Gemini call:\n{prompt[:200]}")
        return self._responses.pop(0)


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="01HZZ",
        topic="the history of espresso",
        format="short",
        visibility="public",
        run_dir=tmp_path,
        artifacts={},
        metadata={"seed": 42},
    )


@pytest.mark.asyncio
async def test_script_agent_writes_well_formed_script_json(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)  # tolerant for tiny fixture
    ctx = _ctx(tmp_path)

    result = await agent.run(ctx)

    script_path = result.artifacts["script.json"]
    assert script_path.exists()
    data = json.loads(script_path.read_text())

    assert data["topic"] == "the history of espresso"
    assert data["format"] == "short"
    assert data["voice_category"] in {
        "calm_narrator", "energetic_explainer", "deep_documentary",
        "warm_storyteller", "mysterious_lowkey",
    }
    assert data["duration_target_s"] == 50
    assert data["narration"] == narration_fixture["narration"]
    assert len(data["scenes"]) == 4
    assert data["youtube"]["title"] == "Espresso at Dawn"
    assert "prompt_params" in data
    assert data["prompt_params"]["seed"] == 42


@pytest.mark.asyncio
async def test_script_agent_computes_scene_timings_from_word_counts(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)

    result = await agent.run(_ctx(tmp_path))
    data = json.loads(result.artifacts["script.json"].read_text())

    scenes = data["scenes"]
    # Scenes must be contiguous: scene[i].end_s == scene[i+1].start_s
    for i in range(len(scenes) - 1):
        assert scenes[i]["end_s"] == pytest.approx(scenes[i + 1]["start_s"])
    # First scene starts at 0
    assert scenes[0]["start_s"] == 0.0
    # Last scene ends near duration_target_s
    assert scenes[-1]["end_s"] == pytest.approx(data["duration_target_s"], abs=0.01)
    # Each scene has visual_prompt and pexels_query merged in
    for sc in scenes:
        assert "visual_prompt" in sc
        assert "pexels_query" in sc


@pytest.mark.asyncio
async def test_script_agent_retries_on_word_count_out_of_tolerance(
    tmp_path: Path,
    scene_visuals_fixture: dict[str, Any],
) -> None:
    too_short = {
        "narration": "Two words only.",
        "scene_breaks": [{"index": 0, "narration_excerpt": "Two words only."}],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    ok = {
        "narration": " ".join(["word"] * 120),
        "scene_breaks": [
            {"index": 0, "narration_excerpt": " ".join(["word"] * 60)},
            {"index": 1, "narration_excerpt": " ".join(["word"] * 60)},
        ],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([too_short, ok, scene_visuals_fixture])
    # Only ok narration fits the default tolerance
    agent = ScriptAgent(gemini=fake)

    await agent.run(_ctx(tmp_path))

    # Two narration prompts (first failed length check, second OK) + one visuals prompt = 3 total
    assert len(fake.prompts) == 3


@pytest.mark.asyncio
async def test_script_agent_fails_after_max_length_retries(
    tmp_path: Path,
) -> None:
    too_short = {
        "narration": "Tiny.",
        "scene_breaks": [{"index": 0, "narration_excerpt": "Tiny."}],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([too_short, too_short, too_short])
    agent = ScriptAgent(gemini=fake, max_length_retries=2)

    with pytest.raises(ValueError, match="word count"):
        await agent.run(_ctx(tmp_path))


@pytest.mark.asyncio
async def test_script_agent_fails_fast_on_zero_scenes(tmp_path: Path) -> None:
    bad = {
        "narration": " ".join(["word"] * 120),
        "scene_breaks": [],
        "youtube": {"title": "x", "description": "y", "tags": ["z"]},
    }
    fake = FakeGemini([bad])
    agent = ScriptAgent(gemini=fake)

    with pytest.raises(ValueError, match="scenes"):
        await agent.run(_ctx(tmp_path))


@pytest.mark.asyncio
async def test_script_agent_metadata_includes_voice_category_and_params(
    tmp_path: Path,
    narration_fixture: dict[str, Any],
    scene_visuals_fixture: dict[str, Any],
) -> None:
    fake = FakeGemini([narration_fixture, scene_visuals_fixture])
    agent = ScriptAgent(gemini=fake, word_count_tolerance=2.0)

    result = await agent.run(_ctx(tmp_path))

    assert "voice_category" in result.metadata
    assert "duration_target_s" in result.metadata
    assert "prompt_params" in result.metadata
    assert result.metadata["prompt_params"]["seed"] == 42
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_script_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.agents'`.

- [ ] **Step 5: Implement `agents/__init__.py`**

`src/yt_auto/agents/__init__.py`: empty file.

- [ ] **Step 6: Implement `agents/script.py`**

`src/yt_auto/agents/script.py`:
```python
"""Script Agent: builds script.json from topic + format using Gemini."""
import json
from dataclasses import asdict
from typing import Any, Protocol

from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext
from yt_auto.prompts.script_meta import (
    PromptParams,
    build_params,
    render_narration_prompt,
    render_scene_visuals_prompt,
    target_duration_seconds,
    target_word_count,
    wps_for_voice,
)

log = get_logger(__name__)


class GeminiLike(Protocol):
    async def generate_json(self, prompt: str) -> dict[str, Any]: ...


class ScriptAgent:
    name = "script"

    def __init__(
        self,
        gemini: GeminiLike,
        *,
        word_count_tolerance: float = 0.10,
        max_length_retries: int = 2,
    ) -> None:
        self._gemini = gemini
        self._tolerance = word_count_tolerance
        self._max_length_retries = max_length_retries

    async def run(self, ctx: RunContext) -> StageResult:
        seed = ctx.metadata.get("seed")
        params = build_params(topic=ctx.topic, video_format=ctx.format, seed=seed)
        word_target = target_word_count(ctx.format, params.voice_category)

        narration_data = await self._generate_narration_with_length_check(
            ctx=ctx, params=params, word_target=word_target
        )

        scenes_timed = self._compute_scene_timings(
            scene_breaks=narration_data["scene_breaks"],
            narration=narration_data["narration"],
            duration_s=target_duration_seconds(ctx.format),
        )

        visuals_data = await self._gemini.generate_json(
            render_scene_visuals_prompt(scenes=scenes_timed)
        )
        scenes_with_visuals = self._merge_visuals(scenes_timed, visuals_data["scenes"])

        script = {
            "topic": ctx.topic,
            "format": ctx.format,
            "voice_category": params.voice_category,
            "duration_target_s": target_duration_seconds(ctx.format),
            "narration": narration_data["narration"],
            "scenes": scenes_with_visuals,
            "youtube": narration_data["youtube"],
            "prompt_params": params.to_dict(),
        }

        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        script_path = ctx.run_dir / "script.json"
        script_path.write_text(json.dumps(script, indent=2))
        log.info("script_written", path=str(script_path), scenes=len(scenes_with_visuals))

        return StageResult(
            artifacts={"script.json": script_path},
            metadata={
                "duration_target_s": script["duration_target_s"],
                "voice_category": params.voice_category,
                "prompt_params": params.to_dict(),
            },
        )

    async def _generate_narration_with_length_check(
        self, *, ctx: RunContext, params: PromptParams, word_target: int
    ) -> dict[str, Any]:
        last_word_count = 0
        for attempt in range(1, self._max_length_retries + 2):  # initial + retries
            prompt = render_narration_prompt(
                topic=ctx.topic,
                video_format=ctx.format,
                params=params,
                word_target=word_target,
            )
            if attempt > 1:
                prompt += (
                    f"\n\nNOTE: your previous attempt was {last_word_count} words. "
                    f"Target is {word_target} (±{int(self._tolerance * 100)}%). "
                    "Adjust length accordingly."
                )
            data = await self._gemini.generate_json(prompt)
            self._validate_narration_shape(data)
            wc = self._word_count(data["narration"])
            if self._within_tolerance(wc, word_target):
                return data
            last_word_count = wc
            log.warning(
                "narration_length_off",
                attempt=attempt,
                got=wc,
                target=word_target,
                tolerance=self._tolerance,
            )
        raise ValueError(
            f"narration word count {last_word_count} stayed outside "
            f"±{int(self._tolerance * 100)}% of target {word_target} after "
            f"{self._max_length_retries} retries"
        )

    @staticmethod
    def _validate_narration_shape(data: dict[str, Any]) -> None:
        for key in ("narration", "scene_breaks", "youtube"):
            if key not in data:
                raise ValueError(f"narration response missing key: {key}")
        if not isinstance(data["scene_breaks"], list) or len(data["scene_breaks"]) == 0:
            raise ValueError("narration response has zero scenes")

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    def _within_tolerance(self, got: int, target: int) -> bool:
        lo = target * (1 - self._tolerance)
        hi = target * (1 + self._tolerance)
        return lo <= got <= hi

    @staticmethod
    def _compute_scene_timings(
        scene_breaks: list[dict[str, Any]],
        narration: str,
        duration_s: int,
    ) -> list[dict[str, Any]]:
        total_words = max(1, len(narration.split()))
        scenes: list[dict[str, Any]] = []
        cursor = 0.0
        for sb in scene_breaks:
            excerpt = sb["narration_excerpt"]
            wc = max(1, len(excerpt.split()))
            duration = duration_s * (wc / total_words)
            scenes.append(
                {
                    "index": sb["index"],
                    "start_s": round(cursor, 3),
                    "end_s": round(cursor + duration, 3),
                    "narration_excerpt": excerpt,
                }
            )
            cursor += duration
        # Snap last scene end_s exactly to duration_s to avoid float drift
        if scenes:
            scenes[-1]["end_s"] = float(duration_s)
        return scenes

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
                    "pexels_query": v["pexels_query"],
                }
            )
        return out


# Quiet "wps unused" — we re-export so callers can reach it through this module.
_ = wps_for_voice
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_script_agent.py -v`
Expected: all six tests PASS.

- [ ] **Step 8: Run all unit tests to confirm nothing regressed**

Run: `uv run pytest -v`
Expected: all unit tests PASS, integration tests deselected by default.

- [ ] **Step 9: Commit**

```bash
git add src/yt_auto/agents tests/conftest.py tests/fixtures tests/unit/test_script_agent.py
git commit -m "Add Script Agent: two-call Gemini pipeline + scene timing + length retry"
```

---

## Task 9 — CLI entrypoint (`cli.py`)

**Files:**
- Create: `src/yt_auto/cli.py`
- Create: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_cli.py`:
```python
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from yt_auto.cli import main


class StubAgent:
    name = "script"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult

        self.ran_with = ctx
        path = ctx.run_dir / "script.json"
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"topic": ctx.topic, "format": ctx.format}))
        return StageResult(artifacts={"script.json": path}, metadata={})


def test_cli_script_subcommand_runs_agent_and_writes_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub = StubAgent()

    def fake_build_agent(_settings: Any) -> StubAgent:
        return stub

    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setattr("yt_auto.cli.build_script_agent", fake_build_agent)
    monkeypatch.setattr(sys, "argv", [
        "yt_auto",
        "script",
        "the history of espresso",
        "--format", "short",
        "--seed", "123",
    ])

    main()

    out = capsys.readouterr().out
    assert "script.json" in out
    # The agent saw the right ctx
    assert stub.ran_with.topic == "the history of espresso"
    assert stub.ran_with.format == "short"
    assert stub.ran_with.metadata["seed"] == 123
    # File exists under tmp_path/<run_id>/script.json
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    assert (runs[0] / "script.json").exists()


def test_cli_requires_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "script", "--format", "short"])
    with pytest.raises(SystemExit):
        main()


def test_cli_validates_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [
        "yt_auto", "script", "topic", "--format", "vertical",
    ])
    with pytest.raises(SystemExit):
        main()


def test_cli_main_is_sync_wrapper() -> None:
    # main() must be callable from non-async context (e.g., a console script)
    assert not asyncio.iscoroutinefunction(main)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt_auto.cli'`.

- [ ] **Step 3: Implement `cli.py`**

`src/yt_auto/cli.py`:
```python
"""Command-line entrypoint. Phase 1 supports only the `script` subcommand."""
import argparse
import asyncio
import sys
from pathlib import Path

from ulid import ULID

from yt_auto.agents.script import ScriptAgent
from yt_auto.clients.gemini import GeminiClient
from yt_auto.config import Settings, get_settings
from yt_auto.logging import configure_logging, get_logger
from yt_auto.pipeline.context import RunContext


def build_script_agent(settings: Settings) -> ScriptAgent:
    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return ScriptAgent(gemini=gemini)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt_auto", description="YouTube automation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    script = sub.add_parser("script", help="Run only the Script Agent and write script.json")
    script.add_argument("topic", help="Video topic, e.g. 'the history of espresso'")
    script.add_argument(
        "--format",
        choices=["long", "short"],
        default="long",
        help="Target video format (default: long)",
    )
    script.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for reproducible parameter selection",
    )
    script.add_argument(
        "--visibility",
        choices=["public", "unlisted", "private"],
        default="public",
        help="Upload visibility (recorded in run context; not used in Phase 1)",
    )

    return parser


async def _run_script_command(args: argparse.Namespace, settings: Settings) -> Path:
    run_id = str(ULID())
    run_dir = settings.outputs_dir / run_id
    ctx = RunContext(
        run_id=run_id,
        topic=args.topic,
        format=args.format,
        visibility=args.visibility,
        run_dir=run_dir,
        artifacts={},
        metadata={"seed": args.seed} if args.seed is not None else {},
    )
    agent = build_script_agent(settings)
    result = await agent.run(ctx)
    return result.artifacts["script.json"]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("cli")

    if args.command == "script":
        out_path = asyncio.run(_run_script_command(args, settings))
        log.info("script_done", path=str(out_path))
        print(f"Wrote {out_path}")
        return

    parser.error(f"unknown command: {args.command}")  # unreachable; argparse enforces
    sys.exit(2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: all four tests PASS.

- [ ] **Step 5: Smoke-check the CLI parser (no API call)**

Run: `uv run python -m yt_auto script --help`
Expected: prints usage with `topic`, `--format`, `--seed`, `--visibility` flags. Exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/yt_auto/cli.py tests/unit/test_cli.py
git commit -m "Add CLI: `python -m yt_auto script <topic> --format <long|short>`"
```

---

## Task 10 — Opt-in integration smoke test (real Gemini call)

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_script_agent_live.py`

- [ ] **Step 1: Create integration package marker**

`tests/integration/__init__.py`: empty file.

- [ ] **Step 2: Write the integration test**

`tests/integration/test_script_agent_live.py`:
```python
"""Live test against the real Gemini API. Run with: pytest -m integration

Skipped when GEMINI_API_KEY is not set so CI can stay clean.
"""
import json
import os
from pathlib import Path

import pytest

from yt_auto.agents.script import ScriptAgent
from yt_auto.clients.gemini import GeminiClient
from yt_auto.pipeline.context import RunContext

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
async def test_script_agent_against_real_gemini(tmp_path: Path) -> None:
    gemini = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    agent = ScriptAgent(gemini=gemini)

    ctx = RunContext(
        run_id="integration-smoke",
        topic="the history of espresso",
        format="short",
        visibility="private",
        run_dir=tmp_path,
        artifacts={},
        metadata={"seed": 7},
    )

    result = await agent.run(ctx)

    data = json.loads(result.artifacts["script.json"].read_text())
    assert len(data["scenes"]) > 0
    assert len(data["narration"].split()) > 50  # short target is 120 ±10%
    assert data["youtube"]["title"]
    assert data["youtube"]["tags"]
    # Visual prompts merged in
    for sc in data["scenes"]:
        assert sc["visual_prompt"]
        assert sc["pexels_query"]
```

- [ ] **Step 3: Verify the test is collected and deselected by default**

Run: `uv run pytest --collect-only -q`
Expected: shows the unit tests; the integration test is collected but skipped/deselected.

- [ ] **Step 4: If you have a Gemini key handy, run it**

Run: `uv run pytest -m integration -v`
Expected (with key set): PASS in ~10-30s. Costs a few cents.
Expected (without key): test is skipped with the reason "GEMINI_API_KEY not set".

- [ ] **Step 5: Commit**

```bash
git add tests/integration
git commit -m "Add opt-in integration smoke test for Script Agent vs real Gemini"
```

---

## Task 11 — Verify the full Phase 1 deliverable

- [ ] **Step 1: Run ruff lint**

Run: `uv run ruff check src tests`
Expected: no errors. If there are warnings, fix them rather than silencing.

- [ ] **Step 2: Run ruff format check**

Run: `uv run ruff format --check src tests`
Expected: all files formatted. If not, run `uv run ruff format src tests` and re-commit.

- [ ] **Step 3: Run mypy**

Run: `uv run mypy src/yt_auto`
Expected: `Success: no issues found`.

- [ ] **Step 4: Run the full unit test suite with coverage**

Run: `uv run pytest --cov=yt_auto --cov-report=term-missing`
Expected: all tests PASS. Coverage on `agents/script.py` and `prompts/script_meta.py` should be >90%.

- [ ] **Step 5: End-to-end manual check (requires Gemini key in `.env`)**

Run: `uv run python -m yt_auto script "the history of espresso" --format short --seed 42`
Expected:
- Exits 0.
- Prints `Wrote outputs/<ulid>/script.json`.
- That file exists and contains a narration, ≥1 scenes with `visual_prompt`+`pexels_query`, a `youtube` block, and `prompt_params.seed == 42`.

- [ ] **Step 6: Confirm reproducibility — same seed yields same params**

Run twice:
```
uv run python -m yt_auto script "anything" --format short --seed 999
uv run python -m yt_auto script "anything" --format short --seed 999
```
Open both `script.json` files. `prompt_params` (tone/structure/narrative_style/hook_style/voice_category/seed) must be identical between the two. The narration text may differ because Gemini itself is non-deterministic.

- [ ] **Step 7: Confirm variety — different seeds yield different params**

Run a couple times without `--seed` and confirm `prompt_params` differs between runs.

- [ ] **Step 8: Tag the phase milestone**

```bash
git tag phase-1-script-agent
```

---

## Notes for the engineer

- **TDD discipline:** every task starts with a failing test you can see fail before any implementation. Don't skip the "run and watch it fail" step — that's how you know the test is wired correctly.
- **Don't add agents beyond Script.** Voice/Media/Caption/Render/Upload are explicitly Phase 2+. Stay focused.
- **`outputs/` is gitignored.** Real `script.json` files from runs should never end up in commits. Tests use `tmp_path`.
- **If a Gemini call costs you anxiety**, set `GEMINI_API_KEY` to an empty string and skip Tasks 10 step 4 and Task 11 steps 5–7. The unit tests stand on their own.
- **`format` parameter naming:** I use `video_format` inside `script_meta.py` to avoid shadowing the Python builtin `format()`. The CLI flag and the RunContext field stay as `format` because that's what the spec calls them.
