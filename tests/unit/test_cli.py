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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt_auto",
            "script",
            "the history of espresso",
            "--format",
            "short",
            "--seed",
            "123",
        ],
    )

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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yt_auto",
            "script",
            "topic",
            "--format",
            "vertical",
        ],
    )
    with pytest.raises(SystemExit):
        main()


def test_cli_main_is_sync_wrapper() -> None:
    # main() must be callable from non-async context (e.g., a console script)
    assert not asyncio.iscoroutinefunction(main)


class StubVoice:
    name = "voice"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult

        self.ran_with = ctx
        dest = ctx.run_dir / "voice.mp3"
        dest.write_bytes(b"x")
        return StageResult(artifacts={"voice.mp3": dest}, metadata={"actual_duration_s": 1.0})


def _seed_run_dir(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(
        json.dumps(
            {
                "topic": "t",
                "format": "short",
                "voice_category": "calm_narrator",
            }
        )
    )


def test_cli_voice_subcommand_loads_run_and_invokes_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "01HZZ"
    _seed_run_dir(run_dir)

    stub = StubVoice()

    def fake_build_voice(_settings: Any) -> Any:
        return stub

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "y")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setattr("yt_auto.cli.build_voice_agent", fake_build_voice)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "voice", "01HZZ"])

    main()

    out = capsys.readouterr().out
    assert "voice.mp3" in out
    assert stub.ran_with.run_id == "01HZZ"
    assert stub.ran_with.topic == "t"


def test_cli_caption_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "caption", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_media_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "media", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_render_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "render", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_pipeline_local_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "pipeline-local", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


class StubUpload:
    name = "upload"

    def __init__(self) -> None:
        self.ran_with: Any = None

    async def run(self, ctx: Any) -> Any:
        from yt_auto.pipeline.base import StageResult

        self.ran_with = ctx
        dest = ctx.run_dir / "upload.json"
        dest.write_text(json.dumps({"video_id": "ABC", "url": "https://example/ABC"}))
        return StageResult(
            artifacts={"upload.json": dest},
            metadata={"youtube_video_id": "ABC", "youtube_url": "https://example/ABC"},
        )


def _seed_full_run_dir(run_dir: Path) -> None:
    """Seed a run_dir as if Phases 1-2 had completed: script.json + final.mp4."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.json").write_text(
        json.dumps(
            {
                "topic": "t",
                "format": "short",
                "voice_category": "calm_narrator",
                "youtube": {
                    "title": "Title",
                    "description": "Desc.",
                    "tags": ["a", "b"],
                },
            }
        )
    )
    (run_dir / "final.mp4").write_bytes(b"FAKE")


def _set_phase2_env(monkeypatch: pytest.MonkeyPatch, outputs: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "y")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("OUTPUTS_DIR", str(outputs))


def test_cli_upload_subcommand_loads_run_and_invokes_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "01HUP"
    _seed_full_run_dir(run_dir)
    _set_phase2_env(monkeypatch, tmp_path)

    stub = StubUpload()

    def fake_build_upload(_settings: Any) -> Any:
        return stub

    monkeypatch.setattr("yt_auto.cli.build_upload_agent", fake_build_upload)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "upload", "01HUP", "--visibility", "unlisted"])

    main()

    out = capsys.readouterr().out
    assert "upload.json" in out
    assert stub.ran_with.run_id == "01HUP"
    assert stub.ran_with.visibility == "unlisted"


def test_cli_youtube_login_subcommand_invokes_run_oauth_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_phase2_env(monkeypatch, tmp_path)
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRETS_FILE", str(creds))
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "tok.json"))

    calls: list[dict[str, Any]] = []

    def fake_login(credentials_file: Path, token_file: Path) -> None:
        calls.append({"credentials_file": credentials_file, "token_file": token_file})
        token_file.write_text("{}")

    monkeypatch.setattr("yt_auto.cli.run_oauth_login", fake_login)
    monkeypatch.setattr(sys, "argv", ["yt_auto", "youtube-login"])

    main()

    out = capsys.readouterr().out
    assert "tok.json" in out
    assert len(calls) == 1
    assert calls[0]["credentials_file"] == creds


def test_cli_pipeline_full_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "pipeline-full", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_upload_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "upload", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_cli_youtube_login_subcommand_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["yt_auto", "youtube-login", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
