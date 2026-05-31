import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from yt_auto.cli import main


class StubAgent:
    name = "script"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult

        self.ran_with = ctx
        path = ctx.run_dir / "script.json"
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"topic": ctx.topic, "format": ctx.format}))
        return StageResult(artifacts={"script.json": path}, metadata={})


def test_cli_script_subcommand_runs_agent_and_writes_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub = StubAgent()

    def fake_build_agent(_settings: Any) -> StubAgent:
        return stub

    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setattr("yt_auto.cli.build_script_agent", fake_build_agent)
    monkeypatch.setattr(sys, "argv", [
        "yt_auto",
        "script",
        "the history of espresso",
        "--format", "short",
        "--seed", "123",
    ])

    main()

    out = capsys.readouterr().out
    assert "script.json" in out
    # The agent saw the right ctx
    assert stub.ran_with.topic == "the history of espresso"
    assert stub.ran_with.format == "short"
    assert stub.ran_with.metadata["seed"] == 123
    # File exists under tmp_path/<run_id>/script.json
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    assert (runs[0] / "script.json").exists()


def test_cli_requires_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "script", "--format", "short"])
    with pytest.raises(SystemExit):
        main()


def test_cli_validates_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [
        "yt_auto", "script", "topic", "--format", "vertical",
    ])
    with pytest.raises(SystemExit):
        main()


def test_cli_main_is_sync_wrapper() -> None:
    # main() must be callable from non-async context (e.g., a console script)
    assert not asyncio.iscoroutinefunction(main)
