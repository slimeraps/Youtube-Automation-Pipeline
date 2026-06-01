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

## YouTube setup (one-time)

The Upload Agent talks to the YouTube Data API v3 via OAuth (Installed App / Desktop client). One-time onboarding:

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen** → User Type: External. Fill in app name, your email, and the developer contact email. Add the scope `https://www.googleapis.com/auth/youtube.upload`. Add your own Google account as a test user under "Test users".
4. **APIs & Services → Credentials → Create credentials → OAuth client ID → Application type: Desktop app**.
5. Download the resulting JSON to `assets/youtube_credentials.json` (path is configurable via `YOUTUBE_CLIENT_SECRETS_FILE` in `.env`).
6. Run the login flow once:

   ```
   python -m yt_auto youtube-login
   ```

   A browser tab opens. Sign in with the test-user account, grant the upload scope. A `assets/youtube_token.json` is written.

Both `assets/youtube_credentials.json` and `assets/youtube_token.json` are gitignored. `google-auth` will refresh the token automatically on subsequent runs.

**Quota:** YouTube Data API v3 gives every project 10,000 quota units per day, resetting at midnight Pacific. One upload costs 1,600 units, so you can do up to 6 full uploads per day before being rate-limited. If you hit `YouTubeQuotaError`, wait until reset.

**Test-user expiry:** Google's "External" OAuth consent screen in Testing state expires refresh tokens after 7 days. For long-term use, publish the app (instant for the `youtube.upload` scope — no verification needed) or re-run `youtube-login` weekly.

## Running a full pipeline (with upload)

```
python -m yt_auto pipeline-full "the history of espresso" --format short --visibility private
```

This chains all six agents: Script → Voice → Media → Caption → Render → Upload, and prints the YouTube URL. Use `--visibility private` (or `unlisted`) for first runs until you've spot-checked the output. The default is `public`.

If anything fails after Render, you can resume from the failed stage with `python -m yt_auto upload <run-id>` (the run_id is the ULID directory name under `outputs/`).

## Tests

```bash
uv run pytest                      # unit tests only (fast)
uv run pytest -m integration       # live API tests (costs a few cents)
```
