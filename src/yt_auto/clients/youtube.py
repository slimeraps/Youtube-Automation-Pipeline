"""Async wrapper around the (sync) Google API client for YouTube Data API v3.

Auth: Installed-App OAuth (Desktop app credentials). First-time setup writes a
JSON token; subsequent runs read it and let google-auth refresh transparently.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


PrivacyStatus = Literal["public", "unlisted", "private"]

# YouTube Data API: total tags length (joined by commas) must be <= 500 chars.
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
    content: bytes = getattr(exc, "content", b"") or b""
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    reasons = {
        e.get("reason")
        for e in (data.get("error", {}).get("errors") or [])
        if isinstance(e, dict)
    }
    if reasons & _QUOTA_REASONS:
        return YouTubeQuotaError(
            f"YouTube quota exceeded: {data.get('error', {}).get('message', exc)}"
        )
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
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)  # type: ignore[no-untyped-call]
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

        response = await asyncio.to_thread(_execute)
        video_id = response["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        log.info("youtube_uploaded", video_id=video_id, privacy_status=privacy_status)
        return UploadResult(video_id=video_id, url=url)
