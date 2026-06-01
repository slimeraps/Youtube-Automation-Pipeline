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
