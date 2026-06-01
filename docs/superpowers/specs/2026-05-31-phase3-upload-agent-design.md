# Phase 3 — Upload Agent + YouTube OAuth Design

**Date:** 2026-05-31
**Status:** Approved for implementation
**Author:** brainstormed with Cody
**Parent spec:** [2026-05-30-youtube-automation-pipeline-design.md](2026-05-30-youtube-automation-pipeline-design.md) §5 row 6, §13, §14 step 3

## 1. Goal

Build the sixth and final content-producing agent: an Upload Agent that takes a `final.mp4` + `script.json` from a completed local run and publishes the video to YouTube via the Data API v3, plus the OAuth onboarding flow needed to authorize first-time uploads. After Phase 3, the pipeline produces a live YouTube URL from a topic string end-to-end.

## 2. Decisions locked in during brainstorming

| Decision | Choice |
|---|---|
| YouTube `categoryId` | Hardcoded `22` (People & Blogs). Sensible generic default; not exposed per-run yet. |
| `selfDeclaredMadeForKids` | Hardcoded `false`. Not exposed per-run. |
| OAuth login UX | New CLI subcommand `python -m yt_auto youtube-login` (matches existing Phase 1/2 CLI shape; single entrypoint). |
| Upload mode | Always resumable via `MediaFileUpload(chunksize=-1, resumable=True)`. The official SDK has no separate "simple" upload path for `videos.insert`. |
| Session URI persistence | None. If a network failure interrupts upload mid-stream, the stage fails and Phase 4's executor will retry from scratch. Phase 3 has no executor, so a fresh CLI run is the retry. |
| Per-run visibility | Existing `RunContext.visibility` (`public|unlisted|private`) maps directly to `privacyStatus`. Default unchanged (`public` per parent spec §2; risk accepted). |
| Tags | Taken verbatim from `script.json["youtube"]["tags"]`; truncated from the tail if total length > 500 chars (YouTube API cap), with a warning log. |
| Live integration test | None. Upload costs 1,600 quota units (16% of daily) and leaves debris on the channel even when private. Unit tests with a mocked SDK cover the contract; first real `pipeline-full` run validates auth. |
| Token refresh | Rely on `google-auth`'s transparent refresh. Refreshed token is rewritten to disk on each successful refresh. |
| Quota tracking | Out of scope. A 403 `quotaExceeded` surfaces as `YouTubeQuotaError`; user reads the message. |

## 3. Architecture

One new agent + one new client + three new CLI subcommands. No changes to existing agents or pipeline contracts.

```
┌──────────────────────────┐         ┌──────────────────────────┐
│  cli.py (extended)       │         │  agents/upload.py        │
│  - youtube-login         │────────▶│  UploadAgent             │
│  - upload <run-id>       │         │  - reads final.mp4       │
│  - pipeline-full <topic> │         │  - reads script.json     │
└──────────────────────────┘         │  - writes upload.json    │
            │                        └────────────┬─────────────┘
            ▼                                     │
┌──────────────────────────┐                      ▼
│  clients/youtube.py      │◀─────────────────────┘
│  YouTubeClient           │
│  - upload_video(...)     │
│  run_oauth_login(...)    │──▶ assets/youtube_token.json
│  has_valid_token(...)    │
└──────────────────────────┘
            │
            ▼
   google-api-python-client
   google-auth-oauthlib
            │
            ▼
   YouTube Data API v3
```

Boundaries match Phase 2 conventions: the SDK is imported only inside `clients/youtube.py`; the agent depends on a `Protocol`-shaped `YouTubeClientLike` for testability; CLI builds the client from `Settings`.

## 4. New files

```
src/yt_auto/
├── clients/youtube.py
└── agents/upload.py

tests/unit/
├── test_youtube_client.py
└── test_upload_agent.py

assets/.gitkeep          # ensure directory exists in fresh clones
```

Modified files: `cli.py`, `config.py`, `.env.example`, `pyproject.toml`, `README.md`.

`assets/youtube_credentials.json` (user-provided) and `assets/youtube_token.json` (generated) are already covered by the existing `.gitignore` rule `assets/youtube_token.json` from parent spec §4. **Add a rule for `assets/youtube_credentials.json`** during Phase 3 — currently only the token is gitignored.

## 5. `clients/youtube.py`

```python
"""Async wrapper around the (sync) Google API client for YouTube Data API v3."""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

class YouTubeError(Exception): ...
class YouTubeAuthError(YouTubeError): ...
class YouTubeQuotaError(YouTubeError): ...
class YouTubeUploadError(YouTubeError): ...

PrivacyStatus = Literal["public", "unlisted", "private"]

_MAX_TAGS_TOTAL_CHARS = 500

@dataclass(frozen=True)
class UploadResult:
    video_id: str
    url: str  # f"https://www.youtube.com/watch?v={video_id}"

class YouTubeClient:
    def __init__(
        self,
        credentials_file: Path,
        token_file: Path,
        *,
        _sdk: Any = None,
    ) -> None:
        """Construct an authenticated client.

        If `_sdk` is provided (tests), it's used directly. Otherwise:
        - Loads token_file if present; refreshes if expired-but-refreshable, rewrites file.
        - Raises YouTubeAuthError if no token and no credentials, or if refresh fails.
        - Calls googleapiclient.discovery.build("youtube", "v3", credentials=creds).
        """

    async def upload_video(
        self,
        *,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str = "22",
        privacy_status: PrivacyStatus,
        made_for_kids: bool = False,
    ) -> UploadResult: ...

# Module-level helpers (used by the youtube-login CLI subcommand):
def run_oauth_login(credentials_file: Path, token_file: Path) -> None:
    """InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES).run_local_server(port=0).
    Writes `creds.to_json()` to token_file (plain JSON, not pickle). Creates parent dir if needed.
    Raises YouTubeAuthError if credentials_file missing or invalid."""

def has_valid_token(token_file: Path) -> bool:
    """True if token_file exists and parses; does NOT verify against Google's servers."""
```

**OAuth scope:** `https://www.googleapis.com/auth/youtube.upload` (minimum needed for `videos.insert`). One scope only — broader scopes are out of scope until we add features that need them.

**Upload mechanics:**
- Build the request body as `{"snippet": {title, description, tags, categoryId}, "status": {privacyStatus, selfDeclaredMadeForKids}}`.
- `body["snippet"]["tags"] = _truncate_tags(tags)` where `_truncate_tags` pops from the tail until the joined total length (sum of `len(t)` + commas between) ≤ 500, with a `log.warning("tags_truncated", original=N, kept=M)` if anything was dropped.
- `media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")`.
- `request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)`.
- `response = await asyncio.to_thread(request.execute)`.
- Map `HttpError` exceptions:
  - 403 with `reason in {"quotaExceeded", "rateLimitExceeded"}` → `YouTubeQuotaError`.
  - Anything else from `videos.insert` → `YouTubeUploadError` with the upstream message.
- Returns `UploadResult(video_id=response["id"], url=f"https://www.youtube.com/watch?v={response['id']}")`.

## 6. `agents/upload.py`

```python
"""Upload Agent: publishes final.mp4 to YouTube and records the URL."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from yt_auto.clients.youtube import PrivacyStatus, UploadResult
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

class YouTubeClientLike(Protocol):
    async def upload_video(
        self, *,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: PrivacyStatus,
        made_for_kids: bool,
    ) -> UploadResult: ...

class UploadAgent:
    name = "upload"

    def __init__(self, youtube: YouTubeClientLike, *, category_id: str = "22") -> None:
        self._youtube = youtube
        self._category_id = category_id

    async def run(self, ctx: RunContext) -> StageResult:
        video = ctx.artifacts["final.mp4"]
        script = json.loads(ctx.artifacts["script.json"].read_text())
        yt = script["youtube"]  # KeyError if Script Agent didn't populate it

        result = await self._youtube.upload_video(
            video_path=video,
            title=yt["title"],
            description=yt["description"],
            tags=yt["tags"],
            category_id=self._category_id,
            privacy_status=ctx.visibility,
            made_for_kids=False,
        )

        upload_doc = {
            "video_id": result.video_id,
            "url": result.url,
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "title": yt["title"],
            "privacy_status": ctx.visibility,
            "category_id": self._category_id,
            "made_for_kids": False,
        }
        upload_path = ctx.run_dir / "upload.json"
        upload_path.write_text(json.dumps(upload_doc, indent=2))
        log.info("upload_done", video_id=result.video_id, url=result.url)

        return StageResult(
            artifacts={"upload.json": upload_path},
            metadata={
                "youtube_video_id": result.video_id,
                "youtube_url": result.url,
            },
        )
```

`upload.json` shape (canonical):

```json
{
  "video_id": "dQw4w9WgXcQ",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "uploaded_at": "2026-06-01T03:14:15.926Z",
  "title": "...",
  "privacy_status": "public",
  "category_id": "22",
  "made_for_kids": false
}
```

## 7. CLI additions

```
python -m yt_auto youtube-login
python -m yt_auto upload <run-id> [--visibility public|unlisted|private]
python -m yt_auto pipeline-full <topic> [--format long|short] [--seed N] [--visibility ...]
```

- **`youtube-login`:** no `run_id`. Validates `settings.youtube_client_secrets_file` exists; calls `run_oauth_login(...)`; prints the resulting token path. Distinct argparse handler (not the `_run_single_agent_on_existing` path).
- **`upload`:** standard `_run_single_agent_on_existing` shape with a new `build_upload_agent(settings)` that constructs `YouTubeClient(settings.youtube_client_secrets_file, settings.youtube_token_file)` and `UploadAgent(youtube=client, category_id=settings.youtube_category_id)`.
- **`pipeline-full`:** body of existing `_run_pipeline_local` followed by `ctx.merge(await upload_agent.run(ctx))`. Returns `result.artifacts["upload.json"]`. `pipeline-local` is unchanged — it remains callable without YouTube auth so the offline path stays useful for debugging.

`load_run_context_from_disk` already includes `upload.json` in its `_KNOWN_ARTIFACT_FILES` tuple; no change needed there.

## 8. Settings additions (`config.py`)

```python
# --- Upload ---
youtube_client_secrets_file: Path = Field(default=Path("./assets/youtube_credentials.json"))
youtube_token_file:          Path = Field(default=Path("./assets/youtube_token.json"))
youtube_category_id:         str  = Field(default="22")
```

`.env.example` gets the matching three lines (mirroring parent spec §12's `--- Upload ---` block, but with the corrected key names).

## 9. Dependencies (`pyproject.toml`)

Add to `[project].dependencies`:

```toml
"google-api-python-client>=2.140",
"google-auth-oauthlib>=1.2",
"google-auth-httplib2>=0.2",
```

Add mypy overrides:

```toml
[[tool.mypy.overrides]]
module = "googleapiclient.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "google_auth_oauthlib.*"
ignore_missing_imports = true
```

(`google.auth.*` already has typing stubs and doesn't need an override.)

## 10. Error handling

| Failure | Surfaced as | Caller sees |
|---|---|---|
| `assets/youtube_credentials.json` missing | `YouTubeAuthError` at `YouTubeClient.__init__` | Instruction to download from Google Cloud Console |
| `assets/youtube_token.json` missing | `YouTubeAuthError` at `YouTubeClient.__init__` | Instruction: `python -m yt_auto youtube-login` |
| Token expired, refresh fails | Catches `RefreshError`, deletes broken token, raises `YouTubeAuthError` | Instruction to re-run `youtube-login` |
| `script.json` lacks `youtube` block | `KeyError` from agent | Fail-fast; Script Agent contract violation |
| `final.mp4` missing from `ctx.artifacts` | `KeyError` from agent | Earlier stage didn't run |
| 403 `quotaExceeded` / `rateLimitExceeded` | `YouTubeQuotaError` from client | "Upload quota exceeded; resets at midnight Pacific" |
| 5xx / other HttpError from `videos.insert` | `YouTubeUploadError` from client | Upstream message |
| Network drop mid-upload | `YouTubeUploadError` (SDK's internal chunk retry exhausted) | Re-run `upload <run-id>` to retry from scratch |
| Tags total > 500 chars | Truncated from tail, `log.warning("tags_truncated")` | Warning in logs; upload proceeds |

No client-side retry loop in Phase 3. The resumable SDK retries chunks internally; stage-level retry is the Phase 4 executor's responsibility.

## 11. Test plan

**`tests/unit/test_youtube_client.py`:**
- `_FakeYouTubeSDK` exposing `.videos().insert(...).execute()` returning `{"id": "FAKE_ID"}`.
- `upload_video` happy path → returns `UploadResult("FAKE_ID", "https://www.youtube.com/watch?v=FAKE_ID")`.
- 403 with `reason="quotaExceeded"` → `YouTubeQuotaError`.
- 403 with other reason → `YouTubeUploadError`.
- 500 → `YouTubeUploadError`.
- Tags totaling 700 chars → truncated to ≤500, warning logged, upload still proceeds; verify the body passed to `insert(...)` has the trimmed list.
- `has_valid_token` true on valid JSON token file, false on missing file, false on unparseable file.
- `run_oauth_login` raises `YouTubeAuthError` when `credentials_file` is missing. (Happy path is not unit-tested — it opens a real browser.)

**`tests/unit/test_upload_agent.py`:**
- `_FakeYouTube` returning a canned `UploadResult`; provide a fixture `script.json` with a `youtube` block + a dummy `final.mp4` (empty file is fine; agent doesn't read its bytes).
- Asserts `upload.json` written with the canonical shape from §6.
- Asserts returned `StageResult.metadata["youtube_video_id"]` and `["youtube_url"]`.
- Asserts `privacy_status` matches `ctx.visibility` for all three values (public/unlisted/private).
- Missing `script.json["youtube"]` → `KeyError`.

**`tests/unit/test_cli.py` (extension):**
- `youtube-login` subcommand parses without `run_id`.
- `upload` subcommand uses the `_run_single_agent_on_existing` shape.
- `pipeline-full` accepts `topic` + format/seed/visibility.

**`tests/unit/test_config.py` (extension):**
- `Settings` exposes `youtube_client_secrets_file`, `youtube_token_file`, `youtube_category_id` with the documented defaults.

**No integration tests.** First real `pipeline-full` run validates the OAuth wiring end-to-end.

## 12. README addition

Two new sections, placed after the existing setup section:

> ### YouTube setup (one-time)
>
> 1. Open [Google Cloud Console](https://console.cloud.google.com/), create or pick a project.
> 2. **APIs & Services → Library** → enable **YouTube Data API v3**.
> 3. **APIs & Services → OAuth consent screen** → External, fill in app name + your email + dev contact, add scope `youtube.upload`. Add your Google account as a test user.
> 4. **APIs & Services → Credentials → Create credentials → OAuth client ID → Desktop app**.
> 5. Download the JSON to `assets/youtube_credentials.json`.
> 6. Run `python -m yt_auto youtube-login`. A browser opens; sign in with the test-user account; grant the upload scope. A `assets/youtube_token.json` is written.
>
> Both files are gitignored.
>
> ### Running a full pipeline (with upload)
>
> ```
> python -m yt_auto pipeline-full "the history of espresso" --format short --visibility private
> ```
>
> This runs Script → Voice → Media → Caption → Render → Upload and prints the YouTube URL. Use `--visibility private` for first runs until you trust the output.

## 13. Out of scope

- Thumbnail upload
- Caption/subtitle sidecar upload (captions are burned into the video)
- Playlist add / channel section management
- Analytics or quota-usage queries
- Multi-channel support (single channel == whatever the OAuth account owns)
- Quota tracking / pre-flight quota check
- Per-stage retry policy (deferred to Phase 4 executor)
- Persisted resumable-upload session URIs (deferred to Phase 4 executor)
- Per-run `category_id` / `made_for_kids` overrides (could be added as CLI flags later if needed)

## 14. Risks & follow-ups

- **First real upload is public by default.** Reiterating parent spec §16's warning: until the first few real runs have been spot-checked, prefer `--visibility private` or `unlisted`. The CLI default is intentionally `public` to match parent spec §2.
- **OAuth test-user expiry.** Google's "External" OAuth consent screen in Testing state expires refresh tokens after 7 days. For long-term use, either publish the app (instant for `youtube.upload` scope — no verification needed) or live with re-running `youtube-login` weekly.
- **Quota lockout.** 10,000 units/day = 6 full uploads/day before lockout. Cody's expected use is well under this, but if multiple runs fail and retry on the same day this could bite. A future enhancement could read remaining quota from the API before uploading.
- **`pipeline-full` is fire-and-forget.** A successful Script + Voice + Media + Caption + Render followed by a failed Upload leaves the user with a valid `final.mp4` and no upload. They can re-run `python -m yt_auto upload <run-id>` once the failure cause is fixed. This is exactly the resume story the parent spec describes — Phase 4's executor will formalize it.
