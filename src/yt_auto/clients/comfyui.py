"""Thin async client for a local ComfyUI server: submit workflow → poll → download PNG."""

import asyncio
import importlib.resources
import json
import time
from pathlib import Path
from typing import Any

import httpx

from yt_auto.logging import get_logger

log = get_logger(__name__)


class ComfyUIError(Exception):
    """ComfyUI request failed or timed out."""


def _load_workflow_template() -> dict[str, Any]:
    res = importlib.resources.files("yt_auto.clients.workflows") / "sdxl_txt2img.json"
    return json.loads(res.read_text(encoding="utf-8"))


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 180.0,
        poll_interval_s: float = 1.0,
        _http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._http = _http or httpx.AsyncClient(base_url=self._base_url, timeout=30.0)
        self._template = _load_workflow_template()

    def _build_workflow(
        self, *, prompt: str, width: int, height: int, seed: int
    ) -> dict[str, Any]:
        wf = json.loads(json.dumps(self._template))  # deep copy
        wf["3"]["inputs"]["seed"] = int(seed)
        wf["5"]["inputs"]["width"] = int(width)
        wf["5"]["inputs"]["height"] = int(height)
        wf["6"]["inputs"]["text"] = prompt
        return wf

    async def ping(self) -> bool:
        try:
            resp = await self._http.get("/system_stats", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        dest: Path,
    ) -> None:
        wf = self._build_workflow(prompt=prompt, width=width, height=height, seed=seed)
        try:
            resp = await self._http.post("/prompt", json={"prompt": wf})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"submit failed: {exc}") from exc

        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"submit response missing prompt_id: {resp.text[:200]}")

        image_info = await self._poll_until_done(prompt_id)
        await self._download_image(image_info, dest)
        log.info("comfyui_generated", prompt_id=prompt_id, dest=str(dest))

    async def _poll_until_done(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                resp = await self._http.get(f"/history/{prompt_id}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"poll failed: {exc}") from exc
            data = resp.json()
            entry = data.get(prompt_id)
            if entry and entry.get("outputs"):
                images = self._extract_first_image(entry["outputs"])
                if images is not None:
                    return images
            if time.monotonic() >= deadline:
                raise ComfyUIError(f"timeout waiting for prompt {prompt_id}")
            await asyncio.sleep(self._poll_interval_s)

    @staticmethod
    def _extract_first_image(outputs: dict[str, Any]) -> dict[str, Any] | None:
        for node_output in outputs.values():
            for img in node_output.get("images", []) or []:
                return img
        return None

    async def _download_image(self, image_info: dict[str, Any], dest: Path) -> None:
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        try:
            resp = await self._http.get("/view", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"download failed: {exc}") from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
