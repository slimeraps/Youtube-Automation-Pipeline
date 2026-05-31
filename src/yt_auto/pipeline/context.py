"""RunContext: the read-mostly state object threaded through every stage."""
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
