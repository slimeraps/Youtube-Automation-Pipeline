# YouTube Automation Pipeline

Generates a complete narrated video from a single topic string. See
[the design doc](docs/superpowers/specs/2026-05-30-youtube-automation-pipeline-design.md)
for the full architecture.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
# fill in API keys in .env
```

## Phase 1 usage

```bash
uv run python -m yt_auto script "the history of espresso" --format short
```

Writes `outputs/<run_id>/script.json`.

## Tests

```bash
uv run pytest                      # unit tests only (fast)
uv run pytest -m integration       # live API tests (costs a few cents)
```
