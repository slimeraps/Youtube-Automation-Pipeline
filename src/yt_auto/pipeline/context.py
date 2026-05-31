"""RunContext: the read-mostly state object threaded through every stage."""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

VideoFormat = Literal["long", "short"]
Visibility = Literal["public", "unlisted", "private"]


@dataclass
class RunContext:
    run_id: str
    topic: str
    format: VideoFormat
    visibility: Visibility
    run_dir: Path
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def merge(self, result: "StageResult") -> "RunContext":
        """Return a new RunContext with this stage's outputs folded in."""
        return replace(
            self,
            artifacts={**self.artifacts, **result.artifacts},
            metadata={**self.metadata, **result.metadata},
        )


# Late import to avoid circularity
from yt_auto.pipeline.base import StageResult  # noqa: E402

# Logical artifact names that may exist in a run directory at various stages.
_KNOWN_ARTIFACT_FILES = (
    "script.json",
    "voice.mp3",
    "captions.srt",
    "video_silent.mp4",
    "final.mp4",
    "upload.json",
)


def load_run_context_from_disk(run_dir: Path, *, visibility: Visibility) -> RunContext:
    """Rehydrate a RunContext from `outputs/<run_id>/` for resume / per-agent runs.

    Reads script.json for topic/format/voice_category. Discovers existing artifacts
    by filename so later stages can find what earlier stages produced.
    """
    script_path = run_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"script.json not found in {run_dir}")
    script = json.loads(script_path.read_text())

    artifacts: dict[str, Path] = {}
    for name in _KNOWN_ARTIFACT_FILES:
        p = run_dir / name
        if p.exists():
            artifacts[name] = p

    metadata: dict[str, Any] = {}
    if "voice_category" in script:
        metadata["voice_category"] = script["voice_category"]

    return RunContext(
        run_id=run_dir.name,
        topic=script["topic"],
        format=script["format"],
        visibility=visibility,
        run_dir=run_dir,
        artifacts=artifacts,
        metadata=metadata,
    )
