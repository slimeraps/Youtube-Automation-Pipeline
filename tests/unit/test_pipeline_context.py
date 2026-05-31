import json
from pathlib import Path

import pytest

from yt_auto.pipeline.base import StageResult
from yt_auto.pipeline.context import RunContext, load_run_context_from_disk


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


def test_load_run_context_from_disk_rehydrates_minimal_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HZZ"
    run_dir.mkdir()
    (run_dir / "script.json").write_text(json.dumps({
        "topic": "the history of espresso",
        "format": "short",
        "voice_category": "calm_narrator",
    }))

    ctx = load_run_context_from_disk(run_dir, visibility="public")

    assert ctx.run_id == "01HZZ"
    assert ctx.topic == "the history of espresso"
    assert ctx.format == "short"
    assert ctx.run_dir == run_dir
    assert ctx.artifacts == {"script.json": run_dir / "script.json"}
    assert ctx.metadata["voice_category"] == "calm_narrator"


def test_load_run_context_from_disk_includes_existing_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HXX"
    run_dir.mkdir()
    (run_dir / "script.json").write_text(json.dumps({
        "topic": "t", "format": "long", "voice_category": "deep_documentary",
    }))
    (run_dir / "voice.mp3").write_bytes(b"x")
    (run_dir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

    ctx = load_run_context_from_disk(run_dir, visibility="private")

    assert ctx.visibility == "private"
    assert set(ctx.artifacts) == {"script.json", "voice.mp3", "captions.srt"}


def test_load_run_context_from_disk_missing_script_raises(tmp_path: Path) -> None:
    run_dir = tmp_path / "01HQQ"
    run_dir.mkdir()
    with pytest.raises(FileNotFoundError, match=r"script\.json"):
        load_run_context_from_disk(run_dir, visibility="public")
