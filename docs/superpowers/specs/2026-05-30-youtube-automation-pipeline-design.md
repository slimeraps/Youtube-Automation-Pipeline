# YouTube Automation Pipeline — Design

**Date:** 2026-05-30
**Status:** Approved for implementation
**Author:** brainstormed with Cody

## 1. Goal

Build a Python pipeline that takes a single topic string and produces a ready-to-upload YouTube video. The pipeline runs six agents in sequence (Script → Voice → Media → Caption → Render → Upload). The same topic must yield a different video every time, driven by randomized story-shape parameters in the Script Agent. A FastAPI web UI lets the user submit jobs, watch live progress, retry failed stages, and download intermediate artifacts.

## 2. Decisions locked in during brainstorming

| Decision | Choice |
|---|---|
| Video format | Both 16:9 long-form (1920x1080) and 9:16 shorts (1080x1920), selectable per run |
| Orchestration | FastAPI + in-process async pipeline + SQLite job store, with resume-from-last-failed-stage |
| Secrets | `.env` + `pydantic-settings` |
| Whisper | `faster-whisper` local, CPU, `small` model default |
| Music | None — narration only |
| ElevenLabs voice | Script Agent emits a `voice_category` (weighted by chosen tone); Voice Agent maps category → `voice_id` from `.env` |
| YouTube upload | Default `public`, overridable per-job to `unlisted` / `private` |
| Testing | Unit tests with mocked clients + one opt-in `@pytest.mark.integration` smoke test |
| Concurrency | One job at a time (`MAX_CONCURRENT_JOBS=1`) |
| Auth on web UI | None — localhost only; README warns against exposing it |

## 3. Architecture

One FastAPI process serves the UI, owns a SQLite job store, and runs an asyncio worker loop that pulls queued/resumable jobs and drives them through a `PipelineExecutor`. The executor invokes six agents in order. Each agent reads inputs from disk under `outputs/<run_id>/`, writes outputs back to disk, and returns a small metadata blob. All durable state is files on disk + rows in SQLite; no in-memory queues, no Redis.

```
Browser ◀── SSE ──▶  FastAPI app  ──▶  JobStore (SQLite)
                          │
                          ▼
                  PipelineExecutor ──▶ Script → Voice → Media → Caption → Render → Upload
                                                            │
                                                            ▼
                                              outputs/<run_id>/ (all artifacts)
```

**Concurrency model:** single worker task started in `app.on_event("startup")`. Polls the store every 2 s. One in-flight job. Crashed/interrupted stages are detected on startup (rows still marked `running`) and marked `failed` with reason "process restart" — user clicks Retry to resume.

## 4. Project structure

```
youtube-automation/
├── .env.example
├── .gitignore                    # outputs/, .env, data/*.db, assets/youtube_token.json
├── README.md
├── pyproject.toml                # uv + ruff + mypy + pytest config
├── docs/superpowers/specs/
│
├── src/yt_auto/
│   ├── config.py                 # pydantic-settings Settings()
│   ├── logging.py                # structlog setup
│   ├── app.py                    # FastAPI app factory + startup hook
│   ├── cli.py                    # `python -m yt_auto.cli ...`
│   │
│   ├── api/
│   │   ├── routes_jobs.py        # POST/GET /jobs, SSE stream, retry/restart/cancel
│   │   ├── routes_ui.py          # serves index.html
│   │   └── routes_artifacts.py   # GET /jobs/{id}/artifacts/{name}
│   ├── web/
│   │   ├── index.html
│   │   └── static/               # css, htmx
│   │
│   ├── pipeline/
│   │   ├── base.py               # Agent protocol, StageResult
│   │   ├── context.py            # RunContext dataclass
│   │   ├── executor.py           # PipelineExecutor
│   │   └── stages.py             # ordered list of agent instances
│   │
│   ├── agents/
│   │   ├── script.py             # Script Agent (built first)
│   │   ├── voice.py
│   │   ├── media.py
│   │   ├── caption.py
│   │   ├── render.py
│   │   └── upload.py
│   │
│   ├── prompts/
│   │   ├── script_meta.py        # parameter pools + build_params(seed)
│   │   └── templates/
│   │       ├── narration.j2
│   │       └── scene_visuals.j2
│   │
│   ├── clients/                  # thin async wrappers — sole place SDKs are imported
│   │   ├── gemini.py
│   │   ├── elevenlabs.py
│   │   ├── pexels.py
│   │   ├── whisper.py
│   │   └── youtube.py            # OAuth + Data API v3
│   │
│   ├── store/
│   │   ├── db.py                 # aiosqlite engine + migrations runner
│   │   ├── migrations/           # NNNN_*.sql
│   │   ├── models.py             # Job, StageRun, Artifact dataclasses
│   │   └── job_store.py
│   │
│   └── ffmpeg/
│       ├── probe.py
│       ├── concat.py
│       └── render.py
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/                 # canned API responses
│   ├── unit/
│   └── integration/              # @pytest.mark.integration
│
├── outputs/                      # gitignored — one folder per run
├── assets/                       # gitignored — OAuth client secret + token
└── data/jobs.db                  # gitignored — SQLite job store
```

Rationale:
- `src/` layout forces tests to import the installed package — surfaces relative-path bugs early.
- `clients/` is a hard boundary so each external API is mockable in one place.
- `prompts/` is its own package because the dynamic prompt system will be the most-iterated piece of the project.
- `ffmpeg/` wraps shell invocations so flags live in one place and agents stay clean.

## 5. Agent contract

```python
# pipeline/base.py
class Agent(Protocol):
    name: str                            # "script", "voice", "media", "caption", "render", "upload"
    async def run(self, ctx: RunContext) -> StageResult: ...

@dataclass
class StageResult:
    artifacts: dict[str, Path]           # logical name -> file under outputs/<run_id>/
    metadata: dict[str, Any]             # JSON-safe values persisted to DB
```

```python
# pipeline/context.py
@dataclass
class RunContext:
    run_id: str                          # ULID
    topic: str
    format: Literal["long", "short"]
    visibility: Literal["public", "unlisted", "private"]
    run_dir: Path                        # outputs/<run_id>/
    artifacts: dict[str, Path]           # accumulated across stages
    metadata: dict[str, Any]             # accumulated across stages

    def merge(self, result: StageResult) -> "RunContext": ...
```

### Stage I/O table

| # | Stage | Reads from ctx | Writes to disk | Adds to metadata |
|---|---|---|---|---|
| 1 | Script | `topic`, `format`, `seed?` | `script.json` | `duration_target_s`, `voice_category`, `prompt_params` |
| 2 | Voice | `script.json`, `voice_category` | `voice.mp3` | `voice_id`, `actual_duration_s` |
| 3 | Media | `script.json`, `voice.mp3`, `format` | `footage/*.mp4`, `video_silent.mp4` | `clip_count` |
| 4 | Caption | `voice.mp3` | `captions.srt` | `word_count` |
| 5 | Render | `video_silent.mp4`, `voice.mp3`, `captions.srt` | `final.mp4` | `final_duration_s`, `file_size_mb` |
| 6 | Upload | `final.mp4`, `script.json` | `upload.json` | `youtube_video_id`, `youtube_url` |

### `script.json` shape

```json
{
  "topic": "...",
  "format": "long",
  "voice_category": "calm_narrator",
  "duration_target_s": 600,
  "narration": "Full ~10-minute narration text as one string.",
  "scenes": [
    {
      "index": 0,
      "start_s": 0.0,
      "end_s": 12.5,
      "narration_excerpt": "the words spoken during this scene",
      "visual_prompt": "wide aerial shot of a misty forest at dawn",
      "pexels_query": "misty forest aerial dawn"
    }
  ],
  "youtube": {
    "title": "...",
    "description": "...",
    "tags": ["...", "..."]
  },
  "prompt_params": {
    "tone": "contemplative",
    "structure": "three_act",
    "narrative_style": "second_person_immersive",
    "hook_style": "cold_open_question",
    "seed": 1837461
  }
}
```

`prompt_params` is persisted so any run is reproducible: passing the same `seed` to a future run yields the same parameter choices.

Scene `start_s` / `end_s` from the Script Agent are *targets* derived from word counts at ~2.4 wps. They are recomputed by the Media Agent once the real mp3 duration is known (proportional rescale across all scenes).

## 6. Script Agent (first build target)

### Two-call strategy

Single-shot ~10-minute generation is unreliable (truncation, broken JSON, timing drift). Split into two Gemini calls plus a local pass:

1. **Narration call.** Prompt asks for narration + `scene_breaks` (where one visual ends and the next begins) + YouTube metadata. No timing.
2. **Local timing pass.** Compute `start_s`/`end_s` per scene from word counts and a target words-per-second rate (default 2.4 wps; configurable per voice category).
3. **Visual prompts call.** One batched call: pass the whole scenes array, ask for a `visual_prompt` + `pexels_query` per scene, return as JSON array.

Both Gemini calls use `response_mime_type="application/json"` and an explicit `response_schema` to force structured output.

### Dynamic prompt system

```python
# prompts/script_meta.py
TONES = ["contemplative", "urgent", "playful", "ominous",
         "wonder-struck", "deadpan", "warm-mentor", "investigative"]

STRUCTURES = ["three_act", "list_countdown", "chronological_journey",
              "question_then_answer", "myth_vs_reality", "zoom_in_zoom_out"]

NARRATIVE_STYLES = ["second_person_immersive", "third_person_omniscient",
                    "first_person_observer", "documentary_clinical",
                    "campfire_storyteller"]

HOOK_STYLES = ["cold_open_question", "shocking_statistic",
               "in_medias_res_scene", "contrarian_claim", "paradox"]

VOICE_CATEGORIES = ["calm_narrator", "energetic_explainer", "deep_documentary",
                    "warm_storyteller", "mysterious_lowkey"]
```

`build_params(topic, format, seed)` uses a seeded `random.Random` to pick one value from each pool. `voice_category` selection is weighted by chosen tone (e.g., "ominous" → 70% chance of `deep_documentary` or `mysterious_lowkey`). All choices are recorded in `prompt_params` for reproducibility.

The picked params are injected into a Jinja meta-prompt template that constructs a self-contained instruction for Gemini.

### Length control

- `format="long"` → `duration_target_s = 600` (10 min), word target ≈ 1440 at 2.4 wps.
- `format="short"` → `duration_target_s = 50`, word target ≈ 120.

The prompt states the word target with ±10% tolerance. If the response falls outside tolerance, the agent retries up to 2 times with an explicit corrective follow-up ("your last script was N words, target is M"). Third failure raises and the stage is marked failed.

### Failure modes

| Failure | Response |
|---|---|
| Invalid JSON from Gemini | Retry up to 2 times with same prompt |
| Word count off | Retry with corrective follow-up (up to 2 retries) |
| Rate limit / 5xx | Exponential backoff 1 s → 4 s → 16 s, up to 3 attempts. Handled centrally in `clients/gemini.py` |
| Scene count zero | Fail fast — prompt is broken, retrying won't help |

### Test plan

- **Unit:** `test_script_meta.py` — `build_params(seed=N)` is deterministic; pool-coverage tests assert every option is reachable across many seeds.
- **Unit:** `test_script_agent.py` with a fake `GeminiClient` returning canned responses → assert `script.json` shape, scene timing math, YouTube fields.
- **Unit:** length-retry test — fake client returns under-length once then valid; assert one retry was issued.
- **Integration (opt-in):** real Gemini call on `topic="the history of espresso"`, `format=short`. Asserts JSON parses, scene count > 0, narration length within tolerance. Costs a few cents per run.

## 7. Job store schema

```sql
CREATE TABLE jobs (
  id              TEXT PRIMARY KEY,       -- ULID
  topic           TEXT NOT NULL,
  format          TEXT NOT NULL,          -- 'long' | 'short'
  visibility      TEXT NOT NULL,          -- 'public' | 'unlisted' | 'private'
  seed            INTEGER,                -- nullable
  status          TEXT NOT NULL,          -- 'queued'|'running'|'completed'|'failed'|'cancelled'
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  run_dir         TEXT NOT NULL,
  error           TEXT
);

CREATE TABLE stage_runs (
  job_id          TEXT NOT NULL,
  stage_name      TEXT NOT NULL,
  status          TEXT NOT NULL,          -- 'pending'|'running'|'completed'|'failed'
  started_at      TEXT,
  finished_at     TEXT,
  metadata_json   TEXT,
  error           TEXT,
  PRIMARY KEY (job_id, stage_name)
);

CREATE TABLE artifacts (
  job_id          TEXT NOT NULL,
  stage_name      TEXT NOT NULL,
  logical_name    TEXT NOT NULL,
  path            TEXT NOT NULL,
  bytes           INTEGER,
  PRIMARY KEY (job_id, logical_name)
);
```

Migrations are plain `.sql` files in `store/migrations/`, applied in numeric order at startup.

## 8. HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/` | Single-page UI |
| `POST` | `/jobs` | Body `{topic, format, visibility?, seed?}` → `{job_id}` |
| `GET`  | `/jobs` | List jobs (newest first, paginated) |
| `GET`  | `/jobs/{id}` | Job detail + per-stage status + artifact links |
| `GET`  | `/jobs/{id}/stream` | SSE: stage transitions + log lines until terminal state |
| `POST` | `/jobs/{id}/retry` | Resume from last failed stage |
| `POST` | `/jobs/{id}/restart` | Body `{from_stage}` → wipe stages ≥ from_stage and re-run |
| `POST` | `/jobs/{id}/cancel` | Mark cancelled; worker signaled via `asyncio.Event` |
| `GET`  | `/jobs/{id}/artifacts/{logical_name}` | Stream the artifact file |

## 9. Web UI

Single static `index.html` (no build step). HTMX for form submission and partial updates, plus a tiny vanilla-JS SSE listener. Three views on one page:

- **New job form** — topic textarea, format radio, visibility dropdown, optional seed.
- **Job list** — newest first, status pill, click to select.
- **Job detail** — six stage rows with status icons (⏳ 🔄 ✅ ❌). Running stage shows live log lines. Each artifact is a download link. When complete, `<video>` preview of `final.mp4` and a link to the YouTube URL. Retry / "Restart from…" buttons.

No accounts, no auth — README is explicit that this is localhost-only.

## 10. Error handling

- **Transient API errors** (429, 5xx) handled inside `clients/*` with exponential backoff. Agents see only logical failures.
- **Per-stage failure** is recoverable: job stays in DB, user clicks Retry. Each agent's outputs are idempotent file writes so re-running is safe.
- **Crash recovery** is automatic at startup: any `status='running'` row is rewritten to `failed` with reason "process restart" and becomes eligible for retry.
- **Logging:** `structlog` JSON to stdout, plus per-job log file under `outputs/<run_id>/run.log`. SSE stream tails this file.

## 11. Tooling

- **Python 3.12+**
- **uv** for deps + venv
- **ruff** for lint + format
- **mypy** strict on `src/yt_auto/`
- **pytest** + `pytest-asyncio` + `pytest-cov`; `@pytest.mark.integration` opt-in via `pytest -m integration`

### Dependencies

| Need | Package |
|---|---|
| Config | `pydantic-settings` |
| HTTP server | `fastapi`, `uvicorn[standard]`, `sse-starlette` |
| Templates | `jinja2` |
| DB | `aiosqlite` (raw SQL, no ORM) |
| IDs | `python-ulid` |
| Logging | `structlog` |
| HTTP client | `httpx` |
| Gemini | `google-genai` |
| ElevenLabs | `elevenlabs` |
| Pexels | direct `httpx` |
| Whisper | `faster-whisper` |
| YouTube | `google-api-python-client`, `google-auth-oauthlib` |
| ffmpeg | system binary, invoked via `asyncio.create_subprocess_exec` |

## 12. `.env.example`

```
# --- LLM ---
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# --- Voice ---
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_CALM_NARRATOR=
ELEVENLABS_VOICE_ENERGETIC_EXPLAINER=
ELEVENLABS_VOICE_DEEP_DOCUMENTARY=
ELEVENLABS_VOICE_WARM_STORYTELLER=
ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY=

# --- Footage ---
PEXELS_API_KEY=

# --- Captions ---
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# --- Upload ---
YOUTUBE_CLIENT_SECRETS_FILE=assets/youtube_credentials.json
YOUTUBE_TOKEN_FILE=assets/youtube_token.json

# --- App ---
APP_HOST=127.0.0.1
APP_PORT=8000
DATA_DIR=./data
OUTPUTS_DIR=./outputs
MAX_CONCURRENT_JOBS=1
LOG_LEVEL=INFO
```

## 13. YouTube OAuth

First-time setup: `python -m yt_auto.clients.youtube login` opens a browser, completes OAuth, writes `assets/youtube_token.json`. The google-auth library handles refresh automatically. README documents the Google Cloud project setup (enable YouTube Data API v3, create OAuth client of type "Desktop app", download `youtube_credentials.json`).

## 14. Build order

Each phase is independently runnable and testable.

1. **Skeleton + Script Agent** — project scaffold, `config.py`, `logging.py`, `clients/gemini.py`, `prompts/script_meta.py`, `agents/script.py`, minimal `pipeline/base.py` + `pipeline/context.py`, CLI: `python -m yt_auto.cli script "<topic>" --format long`. Unit tests for agent + meta-prompt. **No FastAPI, no DB, no executor yet.**
2. **Voice + Media + Caption + Render Agents** — one at a time, each callable from the CLI; CLI grows a `pipeline-local` command that chains stages off disk.
3. **Upload Agent + OAuth setup.**
4. **PipelineExecutor + SQLite JobStore + CLI to run the whole chain.**
5. **FastAPI + Web UI** wrapping the executor.

## 15. Out of scope (v1)

- Background music
- Auth on the web UI
- Multi-user / multi-tenancy
- Multiple concurrent jobs
- Thumbnail generation
- Cloud Whisper fallback
- Translations / multi-language scripts

## 16. Risks & open follow-ups

- **Public-by-default uploads:** if Gemini hallucinates or Pexels returns mismatched footage, broken videos go live unattended. Mitigated by easy `visibility=private` override per job; user should consider flipping default after first few real runs.
- **Pexels footage relevance:** keyword-based stock search is imprecise. If clips look generic/off-topic too often, Phase 2 milestone: have Gemini emit multiple alternative queries per scene and rank Pexels results by metadata.
- **ffmpeg on Windows:** must be on `PATH` or path configured in `.env`. README will cover install.
- **YouTube quota:** Data API v3 default quota is 10,000 units/day; an upload is ~1,600 units. Plenty for one user, but worth surfacing in error messages.
