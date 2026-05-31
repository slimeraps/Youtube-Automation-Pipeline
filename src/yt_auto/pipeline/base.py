"""Agent protocol and StageResult — the shared contract for every pipeline stage."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class StageResult:
    """What an agent returns when it finishes successfully."""
    artifacts: dict[str, Path] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    """Every pipeline stage implements this."""
    name: str

    async def run(self, ctx: "RunContext") -> StageResult: ...


# Late import to avoid circularity
from yt_auto.pipeline.context import RunContext  # noqa: E402
