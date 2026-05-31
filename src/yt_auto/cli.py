"""Command-line entrypoint. Phase 1 supports only the `script` subcommand."""

import argparse
import asyncio
import sys
from pathlib import Path

from ulid import ULID

from yt_auto.agents.script import ScriptAgent
from yt_auto.clients.gemini import GeminiClient
from yt_auto.config import Settings, get_settings
from yt_auto.logging import configure_logging, get_logger
from yt_auto.pipeline.context import RunContext


def build_script_agent(settings: Settings) -> ScriptAgent:
    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return ScriptAgent(gemini=gemini)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt_auto", description="YouTube automation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    script = sub.add_parser("script", help="Run only the Script Agent and write script.json")
    script.add_argument("topic", help="Video topic, e.g. 'the history of espresso'")
    script.add_argument(
        "--format",
        choices=["long", "short"],
        default="long",
        help="Target video format (default: long)",
    )
    script.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for reproducible parameter selection",
    )
    script.add_argument(
        "--visibility",
        choices=["public", "unlisted", "private"],
        default="public",
        help="Upload visibility (recorded in run context; not used in Phase 1)",
    )

    return parser


async def _run_script_command(args: argparse.Namespace, settings: Settings) -> Path:
    run_id = str(ULID())
    run_dir = settings.outputs_dir / run_id
    ctx = RunContext(
        run_id=run_id,
        topic=args.topic,
        format=args.format,
        visibility=args.visibility,
        run_dir=run_dir,
        artifacts={},
        metadata={"seed": args.seed} if args.seed is not None else {},
    )
    agent = build_script_agent(settings)
    result = await agent.run(ctx)
    return result.artifacts["script.json"]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("cli")

    if args.command == "script":
        out_path = asyncio.run(_run_script_command(args, settings))
        log.info("script_done", path=str(out_path))
        print(f"Wrote {out_path}")
        return

    parser.error(f"unknown command: {args.command}")  # unreachable; argparse enforces
    sys.exit(2)
