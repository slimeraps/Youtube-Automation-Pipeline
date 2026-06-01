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

        uploaded_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
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
