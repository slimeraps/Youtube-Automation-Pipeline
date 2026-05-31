"""Thin async client for Pexels video search + download."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from yt_auto.logging import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.pexels.com"


@dataclass(frozen=True)
class Clip:
    id: int
    duration_s: int
    width: int
    height: int
    url: str


class PexelsClient:
    def __init__(self, api_key: str, *, _http: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        # Caller may pass a shared client; otherwise we make our own (caller responsible
        # for our lifecycle if they didn't pass one — typically we live inside a
        # short-lived agent call, so cleanup is implicit at process exit).
        self._http = _http or httpx.AsyncClient(timeout=30.0)

    async def search_videos(self, *, query: str, per_page: int) -> list[Clip]:
        resp = await self._http.get(
            f"{_BASE_URL}/videos/search",
            params={"query": query, "per_page": per_page, "orientation": "landscape"},
            headers={"Authorization": self._api_key},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        clips: list[Clip] = []
        for v in data.get("videos", []):
            best = self._pick_best_video_file(v.get("video_files", []))
            if best is None:
                continue
            clips.append(Clip(
                id=int(v["id"]),
                duration_s=int(v["duration"]),
                width=int(best["width"]),
                height=int(best["height"]),
                url=str(best["link"]),
            ))
        log.info("pexels_search", query=query, clip_count=len(clips))
        return clips

    @staticmethod
    def _pick_best_video_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not files:
            return None
        # Prefer HD quality, then largest width.
        ranked = sorted(
            files,
            key=lambda f: (0 if f.get("quality") == "hd" else 1, -int(f.get("width", 0))),
        )
        return ranked[0]

    async def download(self, *, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._http.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        log.info("pexels_downloaded", url=url, dest=str(dest))
