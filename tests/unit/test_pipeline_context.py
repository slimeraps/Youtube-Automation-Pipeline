from pathlib import Path

from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext


def test_run_context_merge_combines_artifacts_and_metadata(tmp_path: Path) -> None:
    ctx = RunContext(
        run_id="01HZZ",
        topic="t",
        format="long",
        visibility="public",
        run_dir=tmp_path,
        artifacts={},
        metadata={"a": 1},
    )
    result = StageResult(
        artifacts={"script.json": tmp_path / "script.json"},
        metadata={"b": 2},
    )

    merged = ctx.merge(result)

    assert merged.artifacts == {"script.json": tmp_path / "script.json"}
    assert merged.metadata == {"a": 1, "b": 2}
    assert merged.run_id == "01HZZ"
    # original ctx untouched
    assert ctx.artifacts == {}
    assert ctx.metadata == {"a": 1}


def test_run_context_merge_later_metadata_wins() -> None:
    ctx = RunContext(
        run_id="01HZZ",
        topic="t",
        format="short",
        visibility="private",
        run_dir=Path("/tmp"),
        artifacts={},
        metadata={"k": "old"},
    )
    result = StageResult(artifacts={}, metadata={"k": "new"})

    merged = ctx.merge(result)

    assert merged.metadata["k"] == "new"
