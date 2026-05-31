"""Command-line entrypoint.

Subcommands:
- script <topic>            run Script Agent for a fresh run
- voice <run-id>            run Voice Agent on an existing run
- caption <run-id>          run Caption Agent on an existing run
- media <run-id>            run Media Agent on an existing run
- render <run-id>           run Render Agent on an existing run
- pipeline-local <topic>    chain script→voice→media→caption→render for a fresh run
"""
import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from ulid import ULID

from yt_auto.agents.caption import CaptionAgent
from yt_auto.agents.media import MediaAgent
from yt_auto.agents.render import RenderAgent
from yt_auto.agents.script import ScriptAgent
from yt_auto.agents.voice import VoiceAgent
from yt_auto.clients.elevenlabs import ElevenLabsClient
from yt_auto.clients.gemini import GeminiClient
from yt_auto.clients.pexels import PexelsClient
from yt_auto.clients.whisper import WhisperClient
from yt_auto.config import Settings, get_settings
from yt_auto.logging import configure_logging, get_logger
from yt_auto.pipeline.base import Agent
from yt_auto.pipeline.context import RunContext, load_run_context_from_disk


def build_script_agent(settings: Settings) -> ScriptAgent:
    gemini = GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return ScriptAgent(gemini=gemini)


def build_voice_agent(settings: Settings) -> VoiceAgent:
    eleven = ElevenLabsClient(api_key=settings.elevenlabs_api_key, model=settings.elevenlabs_model)
    return VoiceAgent(
        elevenlabs=eleven,
        voice_id_for_category=settings.elevenlabs_voice_for_category,
    )


def build_caption_agent(settings: Settings) -> CaptionAgent:
    whisper = WhisperClient(
        model_name=settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    return CaptionAgent(whisper=whisper)


def build_media_agent(settings: Settings) -> MediaAgent:
    pexels = PexelsClient(api_key=settings.pexels_api_key)
    return MediaAgent(pexels=pexels, per_page=settings.pexels_per_page)


def build_render_agent(_settings: Settings) -> RenderAgent:
    return RenderAgent()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt_auto", description="YouTube automation pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    # script
    p_script = sub.add_parser("script", help="Run Script Agent for a fresh run")
    p_script.add_argument("topic")
    p_script.add_argument("--format", choices=["long", "short"], default="long")
    p_script.add_argument("--seed", type=int, default=None)
    p_script.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")

    # voice / caption / media / render — all share the same shape
    for name in ("voice", "caption", "media", "render"):
        p = sub.add_parser(name, help=f"Run {name.capitalize()} Agent on an existing run")
        p.add_argument("run_id", help="ULID of an existing run under outputs/")
        p.add_argument(
            "--visibility", choices=["public", "unlisted", "private"], default="public",
            help="Sets RunContext.visibility (not used until upload phase)",
        )

    # pipeline-local: fresh run, run all 5 in order, no upload
    p_pipe = sub.add_parser(
        "pipeline-local",
        help="Run script→voice→media→caption→render end-to-end locally",
    )
    p_pipe.add_argument("topic")
    p_pipe.add_argument("--format", choices=["long", "short"], default="long")
    p_pipe.add_argument("--seed", type=int, default=None)
    p_pipe.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")

    return parser


def _new_run_context(settings: Settings, args: argparse.Namespace) -> RunContext:
    run_id = str(ULID())
    return RunContext(
        run_id=run_id,
        topic=args.topic,
        format=args.format,
        visibility=args.visibility,
        run_dir=settings.outputs_dir / run_id,
        artifacts={},
        metadata={"seed": args.seed} if args.seed is not None else {},
    )


async def _run_single_agent_on_existing(
    settings: Settings,
    args: argparse.Namespace,
    builder: Callable[[Settings], Agent],
) -> Path:
    run_dir = settings.outputs_dir / args.run_id
    ctx = load_run_context_from_disk(run_dir, visibility=args.visibility)
    agent = builder(settings)
    result = await agent.run(ctx)
    return next(iter(result.artifacts.values()))


async def _run_script(settings: Settings, args: argparse.Namespace) -> Path:
    ctx = _new_run_context(settings, args)
    agent = build_script_agent(settings)
    result = await agent.run(ctx)
    return result.artifacts["script.json"]


async def _run_pipeline_local(settings: Settings, args: argparse.Namespace) -> Path:
    ctx = _new_run_context(settings, args)

    script_agent = build_script_agent(settings)
    ctx = ctx.merge(await script_agent.run(ctx))

    voice_agent = build_voice_agent(settings)
    ctx = ctx.merge(await voice_agent.run(ctx))

    media_agent = build_media_agent(settings)
    ctx = ctx.merge(await media_agent.run(ctx))

    caption_agent = build_caption_agent(settings)
    ctx = ctx.merge(await caption_agent.run(ctx))

    render_agent = build_render_agent(settings)
    result = await render_agent.run(ctx)
    return result.artifacts["final.mp4"]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level)
    log = get_logger("cli")

    if args.command == "script":
        out_path = asyncio.run(_run_script(settings, args))
    elif args.command == "voice":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_voice_agent))
    elif args.command == "caption":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_caption_agent))
    elif args.command == "media":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_media_agent))
    elif args.command == "render":
        out_path = asyncio.run(_run_single_agent_on_existing(settings, args, build_render_agent))
    elif args.command == "pipeline-local":
        out_path = asyncio.run(_run_pipeline_local(settings, args))
    else:
        parser.error(f"unknown command: {args.command}")
        sys.exit(2)

    log.info("done", command=args.command, path=str(out_path))
    print(f"Wrote {out_path}")
