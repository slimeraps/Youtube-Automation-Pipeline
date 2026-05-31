"""Render Agent: mux silent video + narration + burned-in captions → final.mp4."""
from yt_auto.ffmpeg.probe import probe_duration_s
from yt_auto.ffmpeg.render import render_final
from yt_auto.logging import get_logger
from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext

log = get_logger(__name__)

_DIMS_BY_FORMAT: dict[str, tuple[int, int]] = {
    "long": (1920, 1080),
    "short": (1080, 1920),
}
_FPS = 30
_VIDEO_BITRATE = "8M"
_AUDIO_BITRATE = "192k"


class RenderAgent:
    name = "render"

    async def run(self, ctx: RunContext) -> StageResult:
        width, height = _DIMS_BY_FORMAT[ctx.format]
        dest = ctx.run_dir / "final.mp4"

        await render_final(
            video=ctx.artifacts["video_silent.mp4"],
            audio=ctx.artifacts["voice.mp3"],
            subtitles=ctx.artifacts["captions.srt"],
            dest=dest,
            width=width, height=height,
            video_bitrate=_VIDEO_BITRATE, audio_bitrate=_AUDIO_BITRATE,
            fps=_FPS,
        )

        duration = await probe_duration_s(dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        log.info("render_done", path=str(dest), duration_s=duration, size_mb=size_mb)

        return StageResult(
            artifacts={"final.mp4": dest},
            metadata={
                "final_duration_s": duration,
                "file_size_mb": size_mb,
            },
        )
