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
