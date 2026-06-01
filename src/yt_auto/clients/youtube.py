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
