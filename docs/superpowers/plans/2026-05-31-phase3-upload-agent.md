# Phase 3 — Upload Agent + YouTube OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the sixth and final content agent (Upload) plus the OAuth onboarding subcommand needed to authorize it, so that `python -m yt_auto pipeline-full "<topic>"` produces a live YouTube URL end-to-end.

**Architecture:** Add one client (`clients/youtube.py`) wrapping `google-api-python-client` + `google-auth-oauthlib` in the same sync-SDK-in-`asyncio.to_thread` pattern as `clients/elevenlabs.py`. Add one agent (`agents/upload.py`) that reads `final.mp4` + `script.json["youtube"]`, calls the client, writes `upload.json`. Extend the existing CLI with three new subcommands (`youtube-login`, `upload <run-id>`, `pipeline-full <topic>`). No FastAPI, no executor — those are Phases 4 and 5.

**Tech Stack:** `google-api-python-client>=2.140`, `google-auth-oauthlib>=1.2`, `google-auth-httplib2>=0.2`. Auth via Installed-App / Desktop OAuth flow writing JSON token to `assets/youtube_token.json`.

**Spec reference:** [docs/superpowers/specs/2026-05-31-phase3-upload-agent-design.md](../specs/2026-05-31-phase3-upload-agent-design.md).

**Phase 3 decisions locked in during brainstorming:**
- `categoryId` hardcoded to `22` (People & Blogs). Configurable via `Settings.youtube_category_id` but not exposed per-run.
- `selfDeclaredMadeForKids` hardcoded to `false`. Not exposed at all.
- OAuth login is a new top-level CLI subcommand (`python -m yt_auto youtube-login`), not a sub-module entry, to match Phase 1/2 conventions.
- Always-resumable upload via `MediaFileUpload(chunksize=-1, resumable=True)`. The SDK has no separate "simple" upload path for `videos.insert`.
- Per-run visibility from `RunContext.visibility` → `privacyStatus`.
- Tags taken verbatim from `script.json["youtube"]["tags"]`, truncated from the tail if `len(",".join(tags)) > 500` (YouTube cap).
- No live integration test for upload (1,600 quota units + channel debris). Unit tests with a mocked SDK cover the contract.
- `google-auth` handles token refresh transparently; refreshed token is rewritten to disk.

**Environment note:** PowerShell shell; `uv` lives at `C:\Users\Cody\.local\bin\uv.exe`. All commands below use `& "$env:USERPROFILE\.local\bin\uv.exe"`. Bash users: substitute `~/.local/bin/uv.exe`. Branch is `main`; commit directly. Last tag is `0.0.28`; Phase 3 tasks tag `0.0.29` upward; milestone tag `phase-3-upload` after the final task.

**Pre-flight check:** `assets/youtube_credentials.json` is already in `.gitignore`. No `.gitignore` changes needed.

---

## Task 1 — Extend Settings + `.env.example` for Phase 3

**Files:**
- Modify: `src/yt_auto/config.py`
- Modify: `.env.example`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Append the new keys to `.env.example`**

Append to the end of `.env.example` (after the `LOG_LEVEL=INFO` line):

```
# --- Upload (YouTube Data API v3) ---
YOUTUBE_CLIENT_SECRETS_FILE=./assets/youtube_credentials.json
YOUTUBE_TOKEN_FILE=./assets/youtube_token.json
YOUTUBE_CATEGORY_ID=22
```

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_config.py`:

```python
def test_settings_loads_phase3_youtube_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")

    settings = Settings()

    assert settings.youtube_client_secrets_file == Path("./assets/youtube_credentials.json")
    assert settings.youtube_token_file == Path("./assets/youtube_token.json")
    assert settings.youtube_category_id == "22"


def test_settings_youtube_category_id_overrides_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("YOUTUBE_CATEGORY_ID", "27")

    settings = Settings()

    assert settings.youtube_category_id == "27"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_config.py::test_settings_loads_phase3_youtube_keys -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'youtube_client_secrets_file'`.

- [ ] **Step 4: Extend `Settings`**

In `src/yt_auto/config.py`, add the three new fields just before the `# App` section (i.e., between the `# Captions` block and the `# App` block):

```python
    # Upload (YouTube)
    youtube_client_secrets_file: Path = Field(
        default=Path("./assets/youtube_credentials.json"),
        description="OAuth client secrets JSON from Google Cloud Console (Desktop app).",
    )
    youtube_token_file: Path = Field(
        default=Path("./assets/youtube_token.json"),
        description="Generated by youtube-login; refreshed automatically by google-auth.",
    )
    youtube_category_id: str = Field(
        default="22",
        description="YouTube categoryId for uploads. 22=People & Blogs.",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_config.py -v`
Expected: all 6 tests PASS (the 4 existing + 2 new).

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/config.py tests/unit/test_config.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/config.py`
Expected: clean.

- [ ] **Step 7: Commit + tag**

```bash
git add .env.example src/yt_auto/config.py tests/unit/test_config.py
git commit -m "Extend Settings with YouTube credentials/token/category_id keys"
git tag 0.0.29
```

---

## Task 2 — Add Phase 3 dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the three Google SDK deps**

In `pyproject.toml`, extend the `dependencies` block under `[project]` so it reads:

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
    "google-api-python-client>=2.140",
    "google-auth-oauthlib>=1.2",
    "google-auth-httplib2>=0.2",
]
```

- [ ] **Step 2: Add mypy overrides for the new untyped libs**

Append two new override blocks at the end of the `[tool.mypy.overrides]` section (i.e., after the existing `faster_whisper.*` block):

```toml
[[tool.mypy.overrides]]
module = "googleapiclient.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "google_auth_oauthlib.*"
ignore_missing_imports = true
```

(`google.auth.*` and `google.oauth2.*` are typed via their own packages and don't need overrides.)

- [ ] **Step 3: Sync deps**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" sync --extra dev`
Expected: resolves cleanly, installs the three Google SDK packages. ~10 MB of new wheels.

- [ ] **Step 4: Smoke-import the new libs**

Run:
```
& "$env:USERPROFILE\.local\bin\uv.exe" run python -c "from googleapiclient.discovery import build; from googleapiclient.errors import HttpError; from googleapiclient.http import MediaFileUpload; from google_auth_oauthlib.flow import InstalledAppFlow; from google.oauth2.credentials import Credentials; from google.auth.transport.requests import Request; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Confirm existing tests still pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -q`
Expected: 71 passed (the 69 from Phase 2 + 2 new from Task 1), 4 deselected.

- [ ] **Step 6: Commit + tag**

```bash
git add pyproject.toml uv.lock
git commit -m "Add google-api-python-client + google-auth deps; mypy overrides"
git tag 0.0.30
```

---

## Task 3 — `clients/youtube.py` module skeleton: exceptions, dataclass, helpers

This task creates the module with everything **except** the `YouTubeClient` class itself. That gets added in Task 4 once we can test it independently with a fake SDK. Splitting like this lets each task have focused, fast tests.

**Files:**
- Create: `src/yt_auto/clients/youtube.py`
- Create: `tests/unit/test_youtube_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_youtube_client.py`:

```python
"""Tests for yt_auto.clients.youtube — exceptions, helpers, and YouTubeClient.

The full Google SDK is never invoked. YouTubeClient is exercised via the `_sdk`
constructor injection point with a hand-built fake; the auth helpers are tested
against on-disk JSON fixtures."""
import json
from pathlib import Path

import pytest

from yt_auto.clients.youtube import (
    UploadResult,
    YouTubeAuthError,
    YouTubeError,
    has_valid_token,
    run_oauth_login,
)


def test_upload_result_url_is_canonical_watch_link() -> None:
    r = UploadResult(video_id="dQw4w9WgXcQ", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert r.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert r.video_id == "dQw4w9WgXcQ"


def test_youtube_auth_error_is_a_youtube_error() -> None:
    assert issubclass(YouTubeAuthError, YouTubeError)


def test_has_valid_token_false_when_missing(tmp_path: Path) -> None:
    assert has_valid_token(tmp_path / "nope.json") is False


def test_has_valid_token_false_when_unparseable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all{{{")
    assert has_valid_token(bad) is False


def test_has_valid_token_true_when_parseable_json(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({
        "token": "abc", "refresh_token": "xyz",
        "client_id": "...", "client_secret": "...",
    }))
    assert has_valid_token(good) is True


def test_run_oauth_login_raises_when_credentials_file_missing(tmp_path: Path) -> None:
    with pytest.raises(YouTubeAuthError, match="credentials file"):
        run_oauth_login(
            credentials_file=tmp_path / "no_such_creds.json",
            token_file=tmp_path / "out_token.json",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_youtube_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.clients.youtube'`.

- [ ] **Step 3: Implement the module skeleton**

`src/yt_auto/clients/youtube.py`:

```python
"""Async wrapper around the (sync) Google API client for YouTube Data API v3.

Auth: Installed-App OAuth (Desktop app credentials). First-time setup writes a
JSON token; subsequent runs read it and let google-auth refresh transparently.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from yt_auto.logging import get_logger

log = get_logger(__name__)

# Single scope; broader scopes are out of scope until features require them.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeError(Exception):
    """Base class for all YouTube client errors."""


class YouTubeAuthError(YouTubeError):
    """OAuth credentials / token missing, unreadable, or refresh failed."""


class YouTubeQuotaError(YouTubeError):
    """403 quotaExceeded or rateLimitExceeded from the API."""


class YouTubeUploadError(YouTubeError):
    """Any other failure from videos.insert."""


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    url: str


def has_valid_token(token_file: Path) -> bool:
    """True if token_file exists and parses as JSON. Does NOT verify against Google."""
    if not token_file.exists():
        return False
    try:
        json.loads(token_file.read_text())
        return True
    except (json.JSONDecodeError, OSError):
        return False


def run_oauth_login(credentials_file: Path, token_file: Path) -> None:
    """Run the Installed-App OAuth flow and write the resulting token to disk.

    Opens a browser, prompts the user to grant `youtube.upload`, captures the
    callback on a local server (port chosen automatically). Writes
    `creds.to_json()` to token_file (plain JSON, not pickle).

    Raises YouTubeAuthError if credentials_file does not exist.
    """
    if not credentials_file.exists():
        raise YouTubeAuthError(
            f"credentials file not found: {credentials_file}. "
            f"Download a Desktop OAuth client JSON from Google Cloud Console "
            f"and place it at this path."
        )
    # Imported lazily so tests that don't exercise the live flow don't pay the
    # import cost (and so that this module imports cleanly even if google-auth
    # is partially configured).
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    log.info("youtube_oauth_login_complete", token_file=str(token_file))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_youtube_client.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/clients/youtube.py tests/unit/test_youtube_client.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/clients/youtube.py`
Expected: clean.

- [ ] **Step 6: Commit + tag**

```bash
git add src/yt_auto/clients/youtube.py tests/unit/test_youtube_client.py
git commit -m "Add YouTube client skeleton: exceptions, UploadResult, OAuth helpers"
git tag 0.0.31
```

---

## Task 4 — `YouTubeClient.upload_video` (the actual uploader)

Add the `YouTubeClient` class with its constructor (taking a `_sdk` injection point for tests) and the `upload_video` method that wraps `videos().insert(...).execute()` in `asyncio.to_thread`. Map `HttpError`s to the typed exceptions defined in Task 3.

**Files:**
- Modify: `src/yt_auto/clients/youtube.py`
- Modify: `tests/unit/test_youtube_client.py`

- [ ] **Step 1: Update the test file imports + write the failing tests**

In `tests/unit/test_youtube_client.py`, **replace the existing imports at the top** with the expanded set:

```python
"""Tests for yt_auto.clients.youtube — exceptions, helpers, and YouTubeClient.

The full Google SDK is never invoked. YouTubeClient is exercised via the `_sdk`
constructor injection point with a hand-built fake; the auth helpers are tested
against on-disk JSON fixtures."""
import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.clients.youtube import (
    UploadResult,
    YouTubeAuthError,
    YouTubeClient,
    YouTubeError,
    YouTubeQuotaError,
    YouTubeUploadError,
    has_valid_token,
    run_oauth_login,
)
```

Then **append** the new test code below the Task 3 tests:

```python
def _make_http_error(status: int, reason: str) -> Exception:
    """Build a googleapiclient.errors.HttpError with a YouTube-shaped JSON body."""
    from googleapiclient.errors import HttpError

    class _FakeResp:
        def __init__(self, status: int) -> None:
            self.status = status
            self.reason = "fake"

        def __getitem__(self, key: str) -> Any:
            # HttpError reads resp.get("content-type") in some paths.
            return {"content-type": "application/json"}.get(key, "")

        def get(self, key: str, default: Any = None) -> Any:
            return {"content-type": "application/json"}.get(key, default)

    content = json.dumps({
        "error": {
            "code": status,
            "message": f"simulated {reason}",
            "errors": [{"reason": reason, "message": f"simulated {reason}"}],
        }
    }).encode("utf-8")
    return HttpError(_FakeResp(status), content)


class _FakeRequest:
    """Stand-in for the object returned by youtube.videos().insert(...)."""

    def __init__(self, response: dict[str, Any] | None = None,
                 exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.execute_calls = 0

    def execute(self) -> dict[str, Any]:
        self.execute_calls += 1
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


class _FakeVideos:
    def __init__(self, request: _FakeRequest) -> None:
        self._request = request
        self.insert_calls: list[dict[str, Any]] = []

    def insert(self, **kwargs: Any) -> _FakeRequest:
        self.insert_calls.append(kwargs)
        return self._request


class _FakeYouTubeSDK:
    def __init__(self, request: _FakeRequest) -> None:
        self._videos = _FakeVideos(request)

    def videos(self) -> _FakeVideos:
        return self._videos


def _make_dummy_video(tmp_path: Path) -> Path:
    p = tmp_path / "final.mp4"
    p.write_bytes(b"FAKE_MP4_BYTES")
    return p


@pytest.mark.asyncio
async def test_upload_video_happy_path_returns_canonical_result(tmp_path: Path) -> None:
    request = _FakeRequest(response={"id": "FAKE_ID"})
    sdk = _FakeYouTubeSDK(request)
    client = YouTubeClient(
        credentials_file=tmp_path / "creds.json",
        token_file=tmp_path / "tok.json",
        _sdk=sdk,
    )

    result = await client.upload_video(
        video_path=_make_dummy_video(tmp_path),
        title="A title", description="A description.",
        tags=["alpha", "beta"], category_id="22",
        privacy_status="public", made_for_kids=False,
    )

    assert result.video_id == "FAKE_ID"
    assert result.url == "https://www.youtube.com/watch?v=FAKE_ID"
    # The body passed to insert() carries the expected snippet + status.
    body = sdk.videos().insert_calls[0]["body"]
    assert body["snippet"]["title"] == "A title"
    assert body["snippet"]["description"] == "A description."
    assert body["snippet"]["tags"] == ["alpha", "beta"]
    assert body["snippet"]["categoryId"] == "22"
    assert body["status"]["privacyStatus"] == "public"
    assert body["status"]["selfDeclaredMadeForKids"] is False


@pytest.mark.asyncio
async def test_upload_video_403_quota_exceeded_raises_quota_error(tmp_path: Path) -> None:
    request = _FakeRequest(exc=_make_http_error(403, "quotaExceeded"))
    sdk = _FakeYouTubeSDK(request)
    client = YouTubeClient(
        credentials_file=tmp_path / "creds.json",
        token_file=tmp_path / "tok.json",
        _sdk=sdk,
    )

    with pytest.raises(YouTubeQuotaError):
        await client.upload_video(
            video_path=_make_dummy_video(tmp_path),
            title="t", description="d", tags=[],
            category_id="22", privacy_status="private", made_for_kids=False,
        )


@pytest.mark.asyncio
async def test_upload_video_403_other_reason_raises_upload_error(tmp_path: Path) -> None:
    request = _FakeRequest(exc=_make_http_error(403, "forbidden"))
    sdk = _FakeYouTubeSDK(request)
    client = YouTubeClient(
        credentials_file=tmp_path / "creds.json",
        token_file=tmp_path / "tok.json",
        _sdk=sdk,
    )

    with pytest.raises(YouTubeUploadError):
        await client.upload_video(
            video_path=_make_dummy_video(tmp_path),
            title="t", description="d", tags=[],
            category_id="22", privacy_status="private", made_for_kids=False,
        )


@pytest.mark.asyncio
async def test_upload_video_500_raises_upload_error(tmp_path: Path) -> None:
    request = _FakeRequest(exc=_make_http_error(500, "backendError"))
    sdk = _FakeYouTubeSDK(request)
    client = YouTubeClient(
        credentials_file=tmp_path / "creds.json",
        token_file=tmp_path / "tok.json",
        _sdk=sdk,
    )

    with pytest.raises(YouTubeUploadError):
        await client.upload_video(
            video_path=_make_dummy_video(tmp_path),
            title="t", description="d", tags=[],
            category_id="22", privacy_status="private", made_for_kids=False,
        )


@pytest.mark.asyncio
async def test_upload_video_truncates_overlong_tags(tmp_path: Path) -> None:
    # 11 tags of 50 chars each = 550 chars joined (≥10 commas). Joined length:
    # 11*50 + 10 commas = 560 > 500. Truncation pops from the tail.
    big_tags = [("t" + str(i)).ljust(50, "x") for i in range(11)]
    assert len(",".join(big_tags)) > 500

    request = _FakeRequest(response={"id": "FAKE_ID"})
    sdk = _FakeYouTubeSDK(request)
    client = YouTubeClient(
        credentials_file=tmp_path / "creds.json",
        token_file=tmp_path / "tok.json",
        _sdk=sdk,
    )

    await client.upload_video(
        video_path=_make_dummy_video(tmp_path),
        title="t", description="d", tags=big_tags,
        category_id="22", privacy_status="private", made_for_kids=False,
    )

    sent = sdk.videos().insert_calls[0]["body"]["snippet"]["tags"]
    assert len(sent) < len(big_tags)
    assert len(",".join(sent)) <= 500
```

**Note on `pytest.mark.asyncio`:** the test file relies on `asyncio_mode = "auto"` from `pyproject.toml`, so the explicit `@pytest.mark.asyncio` decorators are technically redundant but match the existing Phase 2 test style — keep them for consistency.

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_youtube_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'YouTubeClient' from 'yt_auto.clients.youtube'`.

- [ ] **Step 3: Add `YouTubeClient` to `clients/youtube.py`**

At the top of `src/yt_auto/clients/youtube.py`, add these imports below the existing ones:

```python
import asyncio
from typing import Any, Literal
```

Then append the following to the end of the file (after `run_oauth_login`):

```python
PrivacyStatus = Literal["public", "unlisted", "private"]

_MAX_TAGS_TOTAL_CHARS = 500
_QUOTA_REASONS = frozenset({"quotaExceeded", "rateLimitExceeded"})


def _truncate_tags(tags: list[str], *, max_total: int = _MAX_TAGS_TOTAL_CHARS) -> list[str]:
    """Pop tags from the tail until len(",".join(tags)) <= max_total. Logs a warning."""
    original_len = len(tags)
    result = list(tags)
    while result and len(",".join(result)) > max_total:
        result.pop()
    if len(result) != original_len:
        log.warning("tags_truncated", original=original_len, kept=len(result))
    return result


def _classify_http_error(exc: Any) -> Exception:
    """Map a googleapiclient.errors.HttpError to a typed YouTubeError."""
    content = getattr(exc, "content", b"") or b""
    if isinstance(content, bytes):
        try:
            data = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
    else:
        data = {}
    reasons = {
        e.get("reason")
        for e in (data.get("error", {}).get("errors") or [])
        if isinstance(e, dict)
    }
    if reasons & _QUOTA_REASONS:
        return YouTubeQuotaError(f"YouTube quota exceeded: {data.get('error', {}).get('message', exc)}")
    return YouTubeUploadError(str(exc))


def _load_credentials(credentials_file: Path, token_file: Path) -> Any:
    """Load Credentials from token_file, refresh if needed, rewrite to disk.

    Raises YouTubeAuthError on any failure with a user-actionable message.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not token_file.exists():
        raise YouTubeAuthError(
            f"OAuth token not found at {token_file}. "
            f"Run: python -m yt_auto youtube-login"
        )
    try:
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    except (ValueError, json.JSONDecodeError) as e:
        raise YouTubeAuthError(f"could not read token file {token_file}: {e}") from e

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_file.write_text(creds.to_json())
            log.info("youtube_token_refreshed", token_file=str(token_file))
        except RefreshError as e:
            token_file.unlink(missing_ok=True)
            raise YouTubeAuthError(
                f"token refresh failed ({e}); deleted {token_file}. "
                f"Run: python -m yt_auto youtube-login"
            ) from e

    if not creds.valid:
        raise YouTubeAuthError(
            f"token at {token_file} is not valid. Run: python -m yt_auto youtube-login"
        )
    return creds


class YouTubeClient:
    """Async wrapper around googleapiclient for YouTube Data API v3 uploads."""

    def __init__(
        self,
        credentials_file: Path,
        token_file: Path,
        *,
        _sdk: Any = None,
    ) -> None:
        if _sdk is not None:
            self._sdk = _sdk
            return
        creds = _load_credentials(credentials_file, token_file)
        from googleapiclient.discovery import build

        self._sdk = build("youtube", "v3", credentials=creds, cache_discovery=False)

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
    ) -> UploadResult:
        """Upload `video_path` and return the resulting video_id + URL."""
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": _truncate_tags(tags),
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }

        def _execute() -> dict[str, Any]:
            # Lazy import so tests with `_sdk` injection don't pull googleapiclient.
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(
                str(video_path),
                chunksize=-1,
                resumable=True,
                mimetype="video/mp4",
            )
            request = self._sdk.videos().insert(
                part="snippet,status", body=body, media_body=media,
            )
            try:
                response: dict[str, Any] = request.execute()
                return response
            except HttpError as e:
                raise _classify_http_error(e) from e

        # When _sdk is a fake, the lazy import inside _execute still runs (it just
        # binds names we never use because the fake raises its own pre-built
        # HttpError or returns a plain dict). googleapiclient is a real dep so
        # the import succeeds.
        response = await asyncio.to_thread(_execute)
        video_id = response["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        log.info("youtube_uploaded", video_id=video_id, privacy_status=privacy_status)
        return UploadResult(video_id=video_id, url=url)
```

**Note on the fake SDK and `MediaFileUpload`:** the production code path constructs `MediaFileUpload(str(video_path), ...)` which only does cheap argument validation — it does NOT open the file at construction time. With the `_FakeYouTubeSDK`, `youtube.videos().insert(...)` is the fake `_FakeVideos.insert` that ignores `media_body` and returns the prebuilt `_FakeRequest`, so the real-but-unused `MediaFileUpload` instance is harmless. The 14-byte `b"FAKE_MP4_BYTES"` file in the tests exists so `MediaFileUpload`'s `os.stat` works.

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_youtube_client.py -v`
Expected: all 10 tests PASS (5 from Task 3 + 5 new).

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/clients/youtube.py tests/unit/test_youtube_client.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/clients/youtube.py`
Expected: clean.

- [ ] **Step 6: Commit + tag**

```bash
git add src/yt_auto/clients/youtube.py tests/unit/test_youtube_client.py
git commit -m "Add YouTubeClient.upload_video: resumable upload + typed errors + tag truncation"
git tag 0.0.32
```

---

## Task 5 — Upload Agent (`agents/upload.py`)

**Files:**
- Create: `src/yt_auto/agents/upload.py`
- Create: `tests/unit/test_upload_agent.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_upload_agent.py`:

```python
import json
from pathlib import Path
from typing import Any

import pytest

from yt_auto.agents.upload import UploadAgent
from yt_auto.clients.youtube import PrivacyStatus, UploadResult
from yt_auto.pipeline.context import RunContext


class _FakeYouTube:
    """Captures upload_video kwargs and returns a canned UploadResult."""

    def __init__(self, response: UploadResult | None = None,
                 raise_with: Exception | None = None) -> None:
        self._response = response or UploadResult(
            video_id="VID123", url="https://www.youtube.com/watch?v=VID123",
        )
        self._raise = raise_with
        self.calls: list[dict[str, Any]] = []

    async def upload_video(
        self, *,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: PrivacyStatus,
        made_for_kids: bool,
    ) -> UploadResult:
        self.calls.append({
            "video_path": video_path, "title": title, "description": description,
            "tags": tags, "category_id": category_id,
            "privacy_status": privacy_status, "made_for_kids": made_for_kids,
        })
        if self._raise:
            raise self._raise
        return self._response


def _seed_run(tmp_path: Path, *, visibility: PrivacyStatus = "public") -> RunContext:
    script_path = tmp_path / "script.json"
    final_path = tmp_path / "final.mp4"
    final_path.write_bytes(b"FAKE_MP4")
    script_path.write_text(json.dumps({
        "topic": "the history of espresso",
        "format": "short",
        "voice_category": "calm_narrator",
        "narration": "...",
        "scenes": [],
        "youtube": {
            "title": "A short history of espresso",
            "description": "Three minutes on the bean that built cities.",
            "tags": ["coffee", "history", "espresso"],
        },
    }))
    return RunContext(
        run_id="01HUP", topic="the history of espresso",
        format="short", visibility=visibility,
        run_dir=tmp_path,
        artifacts={"script.json": script_path, "final.mp4": final_path},
        metadata={},
    )


@pytest.mark.asyncio
async def test_upload_agent_uploads_and_writes_upload_json(tmp_path: Path) -> None:
    fake = _FakeYouTube()
    agent = UploadAgent(youtube=fake, category_id="22")

    result = await agent.run(_seed_run(tmp_path, visibility="public"))

    # The client got the right arguments.
    call = fake.calls[0]
    assert call["video_path"] == tmp_path / "final.mp4"
    assert call["title"] == "A short history of espresso"
    assert call["description"] == "Three minutes on the bean that built cities."
    assert call["tags"] == ["coffee", "history", "espresso"]
    assert call["category_id"] == "22"
    assert call["privacy_status"] == "public"
    assert call["made_for_kids"] is False

    # upload.json on disk has the canonical shape.
    upload_path = result.artifacts["upload.json"]
    assert upload_path == tmp_path / "upload.json"
    doc = json.loads(upload_path.read_text())
    assert doc["video_id"] == "VID123"
    assert doc["url"] == "https://www.youtube.com/watch?v=VID123"
    assert doc["title"] == "A short history of espresso"
    assert doc["privacy_status"] == "public"
    assert doc["category_id"] == "22"
    assert doc["made_for_kids"] is False
    # uploaded_at is an ISO-8601 string ending in Z.
    assert isinstance(doc["uploaded_at"], str)
    assert doc["uploaded_at"].endswith("Z")

    # Metadata surfaces both keys.
    assert result.metadata["youtube_video_id"] == "VID123"
    assert result.metadata["youtube_url"] == "https://www.youtube.com/watch?v=VID123"


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "unlisted", "private"])
async def test_upload_agent_propagates_visibility(
    tmp_path: Path, visibility: PrivacyStatus
) -> None:
    fake = _FakeYouTube()
    agent = UploadAgent(youtube=fake)
    await agent.run(_seed_run(tmp_path, visibility=visibility))
    assert fake.calls[0]["privacy_status"] == visibility


@pytest.mark.asyncio
async def test_upload_agent_raises_when_youtube_block_missing(tmp_path: Path) -> None:
    fake = _FakeYouTube()
    agent = UploadAgent(youtube=fake)

    script = tmp_path / "script.json"
    final = tmp_path / "final.mp4"
    final.write_bytes(b"x")
    script.write_text(json.dumps({"topic": "t", "format": "short"}))  # no youtube block
    ctx = RunContext(
        run_id="r", topic="t", format="short", visibility="public",
        run_dir=tmp_path,
        artifacts={"script.json": script, "final.mp4": final},
        metadata={},
    )

    with pytest.raises(KeyError, match="youtube"):
        await agent.run(ctx)


@pytest.mark.asyncio
async def test_upload_agent_uses_constructor_category_id(tmp_path: Path) -> None:
    fake = _FakeYouTube()
    agent = UploadAgent(youtube=fake, category_id="27")
    await agent.run(_seed_run(tmp_path))
    assert fake.calls[0]["category_id"] == "27"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_upload_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yt_auto.agents.upload'`.

- [ ] **Step 3: Implement `upload.py`**

`src/yt_auto/agents/upload.py`:

```python
"""Upload Agent: publishes final.mp4 to YouTube and records the URL."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from yt_auto.clients.youtube import PrivacyStatus, UploadResult
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)


class YouTubeClientLike(Protocol):
    async def upload_video(
        self,
        *,
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

        uploaded_at = (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        upload_doc = {
            "video_id": result.video_id,
            "url": result.url,
            "uploaded_at": uploaded_at,
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_upload_agent.py -v`
Expected: 6 tests PASS (1 happy path + 3 parametrized visibility + 1 missing-block + 1 category_id override = 6).

- [ ] **Step 5: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/agents/upload.py tests/unit/test_upload_agent.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/agents/upload.py`
Expected: clean.

- [ ] **Step 6: Commit + tag**

```bash
git add src/yt_auto/agents/upload.py tests/unit/test_upload_agent.py
git commit -m "Add Upload Agent: YouTube publish + upload.json artifact"
git tag 0.0.33
```

---

## Task 6 — Extend CLI with `youtube-login`, `upload`, `pipeline-full`

The `youtube-login` subcommand has a different shape than the per-agent subcommands (no `run_id`), so it needs its own handler. The `upload` subcommand uses the existing `_run_single_agent_on_existing` helper. The `pipeline-full` subcommand chains all six agents — distinct from `pipeline-local` which stops at render.

**Files:**
- Modify: `src/yt_auto/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
class StubUpload:
    name = "upload"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult

        self.ran_with = ctx
        dest = ctx.run_dir / "upload.json"
        dest.write_text(json.dumps({"video_id": "ABC", "url": "https://example/ABC"}))
        return StageResult(
            artifacts={"upload.json": dest},
            metadata={"youtube_video_id": "ABC", "youtube_url": "https://example/ABC"},
        )


def _seed_full_run_dir(run_dir: Path) -> None:
    """Seed a run_dir as if Phases 1-2 had completed: script.json + final.mp4."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(
        json.dumps(
            {
                "topic": "t",
                "format": "short",
                "voice_category": "calm_narrator",
                "youtube": {
                    "title": "Title",
                    "description": "Desc.",
                    "tags": ["a", "b"],
                },
            }
        )
    )
    (run_dir / "final.mp4").write_bytes(b"FAKE")


def _set_phase2_env(monkeypatch: pytest.MonkeyPatch, outputs: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "y")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("OUTPUTS_DIR", str(outputs))


def test_cli_upload_subcommand_loads_run_and_invokes_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "01HUP"
    _seed_full_run_dir(run_dir)
    _set_phase2_env(monkeypatch, tmp_path)

    stub = StubUpload()

    def fake_build_upload(_settings: Any) -> Any:
        return stub

    monkeypatch.setattr("yt_auto.cli.build_upload_agent", fake_build_upload)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "upload", "01HUP", "--visibility", "unlisted"])

    main()

    out = capsys.readouterr().out
    assert "upload.json" in out
    assert stub.ran_with.run_id == "01HUP"
    assert stub.ran_with.visibility == "unlisted"


def test_cli_youtube_login_subcommand_invokes_run_oauth_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_phase2_env(monkeypatch, tmp_path)
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_FILE", str(creds))
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "tok.json"))

    calls: list[dict[str, Any]] = []

    def fake_login(credentials_file: Path, token_file: Path) -> None:
        calls.append({"credentials_file": credentials_file, "token_file": token_file})
        token_file.write_text("{}")

    monkeypatch.setattr("yt_auto.cli.run_oauth_login", fake_login)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "youtube-login"])

    main()

    out = capsys.readouterr().out
    assert "tok.json" in out
    assert len(calls) == 1
    assert calls[0]["credentials_file"] == creds


def test_cli_pipeline_full_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "pipeline-full", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_upload_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "upload", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_youtube_login_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "youtube-login", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_cli.py -v`
Expected: 5 new tests FAIL with `AttributeError: module 'yt_auto.cli' has no attribute 'build_upload_agent'` / `argument command: invalid choice: 'upload'` / etc.

- [ ] **Step 3: Extend `cli.py`**

In `src/yt_auto/cli.py`:

1. Update the module docstring's subcommand listing to include the three new commands. Replace the existing docstring with:

```python
"""Command-line entrypoint.

Subcommands:
- script <topic>            run Script Agent for a fresh run
- voice <run-id>            run Voice Agent on an existing run
- caption <run-id>          run Caption Agent on an existing run
- media <run-id>            run Media Agent on an existing run
- render <run-id>           run Render Agent on an existing run
- upload <run-id>           run Upload Agent on an existing run (requires youtube-login)
- pipeline-local <topic>    chain script→voice→media→caption→render for a fresh run
- pipeline-full <topic>     chain pipeline-local + upload for a fresh run
- youtube-login             one-time OAuth flow; writes assets/youtube_token.json
"""
```

2. Add the import for `UploadAgent`, `YouTubeClient`, and `run_oauth_login`. Place them with the existing imports so the import block stays alphabetized within each group:

```python
from yt_auto.agents.upload import UploadAgent
from yt_auto.clients.youtube import YouTubeClient, run_oauth_login
```

3. Add a `build_upload_agent` builder. Place it directly after `build_render_agent`:

```python
def build_upload_agent(settings: Settings) -> UploadAgent:
    youtube = YouTubeClient(
        credentials_file=settings.youtube_client_secrets_file,
        token_file=settings.youtube_token_file,
    )
    return UploadAgent(youtube=youtube, category_id=settings.youtube_category_id)
```

4. Extend `_build_parser`. In the per-agent loop, add `"upload"` to the tuple:

```python
    for name in ("voice", "caption", "media", "render", "upload"):
        p = sub.add_parser(name, help=f"Run {name.capitalize()} Agent on an existing run")
        p.add_argument("run_id", help="ULID of an existing run under outputs/")
        p.add_argument(
            "--visibility",
            choices=["public", "unlisted", "private"],
            default="public",
            help="Sets RunContext.visibility",
        )
```

Then add the `pipeline-full` and `youtube-login` parsers immediately after the `pipeline-local` parser block:

```python
    # pipeline-full: fresh run, run all 6 stages including upload
    p_full = sub.add_parser(
        "pipeline-full",
        help="Run script→voice→media→caption→render→upload end-to-end",
    )
    p_full.add_argument("topic")
    p_full.add_argument("--format", choices=["long", "short"], default="long")
    p_full.add_argument("--seed", type=int, default=None)
    p_full.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")

    # youtube-login: one-time OAuth flow
    sub.add_parser(
        "youtube-login",
        help="Run the OAuth login flow and write assets/youtube_token.json",
    )
```

5. Add a `_run_pipeline_full` coroutine after `_run_pipeline_local`:

```python
async def _run_pipeline_full(settings: Settings, args: argparse.Namespace) -> Path:
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
    ctx = ctx.merge(await render_agent.run(ctx))

    upload_agent = build_upload_agent(settings)
    result = await upload_agent.run(ctx)
    return result.artifacts["upload.json"]
```

6. Add a `_run_youtube_login` function. Note this is sync — `run_oauth_login` opens a real browser and blocks, so wrapping it in `asyncio.run` adds nothing:

```python
def _run_youtube_login(settings: Settings) -> Path:
    run_oauth_login(
        credentials_file=settings.youtube_client_secrets_file,
        token_file=settings.youtube_token_file,
    )
    return settings.youtube_token_file
```

7. Extend the `main()` dispatcher. Add the new branches before the final `else`:

```python
    elif args.command == "upload":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_upload_agent))
    elif args.command == "pipeline-full":
        out_path = asyncio.run(_run_pipeline_full(settings, args))
    elif args.command == "youtube-login":
        out_path = _run_youtube_login(settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest tests/unit/test_cli.py -v`
Expected: all CLI tests PASS (the existing 9 + 5 new = 14 total).

- [ ] **Step 5: Smoke-check all new subcommands respond to `--help`**

Run each in turn:
```
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto upload --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto pipeline-full --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto youtube-login --help
```
Expected: each prints usage and exits 0.

- [ ] **Step 6: Run ruff + mypy**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src/yt_auto/cli.py tests/unit/test_cli.py`
Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto/cli.py`
Expected: clean.

- [ ] **Step 7: Commit + tag**

```bash
git add src/yt_auto/cli.py tests/unit/test_cli.py
git commit -m "Extend CLI: youtube-login, upload, and pipeline-full subcommands"
git tag 0.0.34
```

---

## Task 7 — README addition: YouTube setup + running a full pipeline

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Check the current state of README.md**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run cat README.md` (or use the Read tool).
Find the section that documents Phase 2 / the local pipeline (likely a "Usage" or "Running the pipeline" heading). The new YouTube setup section should go after the basic setup but before or alongside the existing pipeline-local documentation.

- [ ] **Step 2: Append the two new sections**

Add the following at an appropriate spot in `README.md`. If the file has a "Usage" / "Running" section already, place these new sections immediately after the existing local-pipeline docs. If not, append to the end of the file.

```markdown
## YouTube setup (one-time)

The Upload Agent talks to the YouTube Data API v3 via OAuth (Installed App / Desktop client). One-time onboarding:

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen** → User Type: External. Fill in app name, your email, and the developer contact email. Add the scope `https://www.googleapis.com/auth/youtube.upload`. Add your own Google account as a test user under "Test users".
4. **APIs & Services → Credentials → Create credentials → OAuth client ID → Application type: Desktop app**.
5. Download the resulting JSON to `assets/youtube_credentials.json` (path is configurable via `YOUTUBE_CLIENT_SECRETS_FILE` in `.env`).
6. Run the login flow once:

   ```
   python -m yt_auto youtube-login
   ```

   A browser tab opens. Sign in with the test-user account, grant the upload scope. A `assets/youtube_token.json` is written.

Both `assets/youtube_credentials.json` and `assets/youtube_token.json` are gitignored. `google-auth` will refresh the token automatically on subsequent runs.

**Quota:** YouTube Data API v3 gives every project 10,000 quota units per day, resetting at midnight Pacific. One upload costs 1,600 units, so you can do up to 6 full uploads per day before being rate-limited. If you hit `YouTubeQuotaError`, wait until reset.

**Test-user expiry:** Google's "External" OAuth consent screen in Testing state expires refresh tokens after 7 days. For long-term use, publish the app (instant for the `youtube.upload` scope — no verification needed) or re-run `youtube-login` weekly.

## Running a full pipeline (with upload)

```
python -m yt_auto pipeline-full "the history of espresso" --format short --visibility private
```

This chains all six agents: Script → Voice → Media → Caption → Render → Upload, and prints the YouTube URL. Use `--visibility private` (or `unlisted`) for first runs until you've spot-checked the output. The default is `public`.

If anything fails after Render, you can resume from the failed stage with `python -m yt_auto upload <run-id>` (the run_id is the ULID directory name under `outputs/`).
```

- [ ] **Step 3: Eyeball the result**

Verify the markdown renders cleanly. No tool check needed; this is text.

- [ ] **Step 4: Commit + tag**

```bash
git add README.md
git commit -m "Document YouTube OAuth setup and pipeline-full usage"
git tag 0.0.35
```

---

## Task 8 — Final Phase 3 verification + milestone tag

- [ ] **Step 1: Run the full unit test suite**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest -v`
Expected: all unit tests PASS, integration tests deselected. The new totals: 69 (Phase 2) + 2 (config) + 5 (youtube client skeleton) + 5 (youtube client upload) + 6 (upload agent) + 5 (cli) = 92 passed, 4 deselected.

If the count is off by 1-2 (parametrize quirks, etc.), inspect — but should be ~92.

- [ ] **Step 2: Run ruff check**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Run ruff format check (and apply if needed)**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format --check src tests`
- If clean: nothing to do.
- If files need formatting: run `& "$env:USERPROFILE\.local\bin\uv.exe" run ruff format src tests`, then commit:
  ```bash
  git add -A
  git commit -m "Apply ruff format across Phase 3 modules"
  ```

- [ ] **Step 4: Run mypy strict**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run mypy src/yt_auto`
Expected: `Success: no issues found in N source files` (N should be ~29 now: the 27 from Phase 2 + `clients/youtube.py` + `agents/upload.py`).

- [ ] **Step 5: Run pytest with coverage**

Run: `& "$env:USERPROFILE\.local\bin\uv.exe" run pytest --cov=yt_auto --cov-report=term-missing`
Expected: total line coverage ≥ 90%. The new modules (`agents/upload.py`, `clients/youtube.py`) should each be ≥ 85% — `_load_credentials` and the live OAuth path of `run_oauth_login` are intentionally not exercised by unit tests, which is OK.

- [ ] **Step 6: Quick manual smoke of every subcommand's `--help`**

Run:
```
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto script --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto voice --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto caption --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto media --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto render --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto upload --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto pipeline-local --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto pipeline-full --help
& "$env:USERPROFILE\.local\bin\uv.exe" run python -m yt_auto youtube-login --help
```
Expected: each exits 0 and prints a sensible usage string.

- [ ] **Step 7: Tag the Phase 3 milestone**

```bash
git tag -a phase-3-upload -m "Phase 3 milestone: Upload Agent + YouTube OAuth onboarding"
```

(Per-task tags `0.0.29` through `0.0.35` already created in earlier tasks.)

- [ ] **Step 8: Push tags (optional, if working with the remote)**

```bash
git push
git push --tags
```

---

## Notes for the engineer

- **TDD discipline:** every implementation step is preceded by a failing-test step. Run the failing-test step and visually confirm the failure mode matches "Expected" before moving on. Skipping the failure check is how broken tests land.
- **`MediaFileUpload` is constructed inside `upload_video` but its `os.stat` runs at construction time.** The unit tests write `b"FAKE_MP4_BYTES"` (14 bytes) to the dummy `final.mp4` so this stat succeeds. If you write a zero-byte file the SDK will complain at construction; if you forget to write the file at all you'll get `FileNotFoundError`.
- **The fake SDK passes `media_body` straight to `_FakeVideos.insert(...)` which records it but doesn't read it.** This is what lets the unit tests use a tiny dummy file without ever exercising real upload code.
- **No live integration test for upload.** First real validation happens on the first `pipeline-full` run, which is the user's call.
- **Default visibility is `public`** — matches parent spec §2. Use `--visibility private` for early runs.
- **The `_load_credentials` function is not directly unit-tested.** Its happy path requires real Google credentials; its error paths are partially covered (missing token file via the constructor's documented behavior). Exercising the refresh-failed branch would require constructing a real-looking `Credentials` object with a bad refresh token, which adds a lot of fixture machinery for one line. Skip it for Phase 3; if it bites later, add a targeted regression test.
- **The OAuth scope is `youtube.upload` only.** Adding playlist management, analytics, or thumbnail upload (all out of scope) would require a broader scope and a re-auth.
- **`youtube-login` is synchronous.** It blocks on the browser callback. Don't try to wrap it in `asyncio.run`.

## Out of scope for Phase 3

- Thumbnail upload (would need `youtube.upload` + `videos.thumbnails.set`)
- Caption / subtitle sidecar upload (captions are burned into the video)
- Playlist add / channel section management
- Analytics or quota-usage queries
- Multi-channel support (single channel = whichever account OAuth'd in)
- Quota tracking / pre-flight quota checks
- Per-stage retry policy (deferred to Phase 4 executor)
- Persisted resumable-upload session URIs (deferred to Phase 4 executor)
- Per-run `category_id` or `made_for_kids` CLI flags
- FastAPI + Web UI (Phase 5)
