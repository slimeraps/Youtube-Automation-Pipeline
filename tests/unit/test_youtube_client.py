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
    good.write_text(
        json.dumps(
            {
                "token": "abc",
                "refresh_token": "xyz",
                "client_id": "...",
                "client_secret": "...",
            }
        )
    )
    assert has_valid_token(good) is True


def test_run_oauth_login_raises_when_credentials_file_missing(tmp_path: Path) -> None:
    with pytest.raises(YouTubeAuthError, match="credentials file"):
        run_oauth_login(
            credentials_file=tmp_path / "no_such_creds.json",
            token_file=tmp_path / "out_token.json",
        )


def _make_http_error(status: int, reason: str) -> Exception:
    """Build a googleapiclient.errors.HttpError with a YouTube-shaped JSON body."""
    from googleapiclient.errors import HttpError

    class _FakeResp:
        def __init__(self, status: int) -> None:
            self.status = status
            self.reason = "fake"

        def __getitem__(self, key: str) -> Any:
            return {"content-type": "application/json"}.get(key, "")

        def get(self, key: str, default: Any = None) -> Any:
            return {"content-type": "application/json"}.get(key, default)

    content = json.dumps(
        {
            "error": {
                "code": status,
                "message": f"simulated {reason}",
                "errors": [{"reason": reason, "message": f"simulated {reason}"}],
            }
        }
    ).encode("utf-8")
    return HttpError(_FakeResp(status), content)


class _FakeRequest:
    """Stand-in for the object returned by youtube.videos().insert(...)."""

    def __init__(
        self, response: dict[str, Any] | None = None, exc: Exception | None = None
    ) -> None:
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
        title="A title",
        description="A description.",
        tags=["alpha", "beta"],
        category_id="22",
        privacy_status="public",
        made_for_kids=False,
    )

    assert result.video_id == "FAKE_ID"
    assert result.url == "https://www.youtube.com/watch?v=FAKE_ID"
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
            title="t",
            description="d",
            tags=[],
            category_id="22",
            privacy_status="private",
            made_for_kids=False,
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
            title="t",
            description="d",
            tags=[],
            category_id="22",
            privacy_status="private",
            made_for_kids=False,
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
            title="t",
            description="d",
            tags=[],
            category_id="22",
            privacy_status="private",
            made_for_kids=False,
        )


@pytest.mark.asyncio
async def test_upload_video_truncates_overlong_tags(tmp_path: Path) -> None:
    # 11 tags of 50 chars each = 550 chars joined. Joined with 10 commas: 560 > 500.
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
        title="t",
        description="d",
        tags=big_tags,
        category_id="22",
        privacy_status="private",
        made_for_kids=False,
    )

    sent = sdk.videos().insert_calls[0]["body"]["snippet"]["tags"]
    assert len(sent) < len(big_tags)
    assert len(",".join(sent)) <= 500
