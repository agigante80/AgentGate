# Copilot Instructions

## Commands

```bash
# Lint
ruff check src/

# Run all tests
pytest tests/ -v --tb=short

# Run a single test file
pytest tests/unit/test_bot.py -v

# Run a single test
pytest tests/unit/test_bot.py::TestPrefix::test_default_prefix -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

## Architecture

TeleAgent is an async Python bot (Telegram **or** Slack) that acts as a gateway to pluggable AI backends. Each deployment is one Docker container per project repo.

**Startup flow** (`src/main.py`): validate config → clone GitHub repo → auto-install deps → init SQLite history DB → create AI backend → start bot (Telegram or Slack) → send 🟢 Ready.

**Config** (`src/config.py`): Pydantic `BaseSettings` split into six sub-configs (`TelegramConfig`, `SlackConfig`, `GitHubConfig`, `BotConfig`, `AIConfig`, `VoiceConfig`). All settings come from env vars. `Settings.load()` constructs them and is the only entry point. `TelegramConfig` fields are optional (default `""`) — validation that they're present happens in `_validate_config()` in `main.py`. Module-level `REPO_DIR` and `DB_PATH` constants are defined here — always import these instead of hardcoding `/repo` or `/data`.

**Platform abstraction** (`src/platform/`):
- `common.py` — shared helpers used by both bots: `build_prompt()` (injects history for stateless backends), `save_to_history()`, `is_allowed_slack()`.
- `slack.py` — `SlackBot` class using `slack-bolt[async]` in Socket Mode. Message events with prefix parsing (e.g. `ta run`, `ta sync`). Streaming via `client.chat_update(ts=…)`. Confirmation dialogs via Block Kit Actions. Voice via file download with auth header.

**Bot handlers** (`src/bot.py`): all Telegram handlers live in `_BotHandlers`. Every handler method is guarded by `@_requires_auth` (checks `TG_CHAT_ID` and optional `ALLOWED_USERS`). Utility commands use the configurable prefix (default `ta`); everything else is forwarded to the AI.

**Platform selection**: `PLATFORM=telegram` (default) uses `src/bot.py`; `PLATFORM=slack` uses `src/platform/slack.py::SlackBot`. Both call the same AI backends, history, executor, and repo modules.
- `adapter.py` defines the `AICLIBackend` ABC: `send()`, `stream()`, `clear_history()`, and the `is_stateful` class-level flag. Also defines `SubprocessMixin` for backends that spawn child processes in `REPO_DIR`.
- `factory.py` selects the concrete backend based on the `AI_CLI` env var (`copilot` | `codex` | `api`).
- `copilot.py` + `session.py` — **stateless** `CopilotBackend` (`is_stateful = False`). `CopilotSession` spawns `copilot -p <prompt> --allow-all` as a subprocess; the bot provides history via context injection.
- `codex.py` — stateful Codex CLI backend.
- `direct.py` — stateless `DirectAPIBackend` for OpenAI / Anthropic / Ollama.

**Stateful vs stateless backends** (`src/bot.py → forward_to_ai`): if `backend.is_stateful` is `True`, the raw prompt is sent directly. If `False`, the last 10 history exchanges from SQLite are prepended via `history.build_context()` before sending.

**Bot handlers** (`src/bot.py`): all Telegram handlers live in `_BotHandlers`. Every handler method is guarded by `@_requires_auth` (checks `TG_CHAT_ID` and optional `ALLOWED_USERS`). Utility commands use the configurable prefix (default `ta`); everything else is forwarded to the AI.

**CI/CD** (`.github/workflows/ci-cd.yml`): single unified pipeline. Jobs: `version` → `lint` + `test` (parallel) → `docker-publish` + `security-scan` → `release` → `summary`. On `develop`: publishes `:develop` Docker tag. On `main`: version-bump check, publishes `:latest`, creates a GitHub Release. Multi-platform builds (amd64 + arm64). `workflow_dispatch` supports `skip_tests` and `skip_docker_publish` inputs.

**History** (`src/history.py`): async SQLite at `/data/history.db`. Stores up to 10 exchanges per `chat_id`. Only used by stateless backends; stateful backends track context themselves.

**Shell execution** (`src/executor.py`): `run_shell()` runs commands in `REPO_DIR`, appends `[exit N]`, and truncates long output (keeping the last N lines). `is_destructive()` keyword-checks commands; `is_exempt()` checks against `BotConfig.skip_confirm_keywords`. `summarize_if_long()` calls the AI backend when output exceeds `max_output_chars`.

**Dependency auto-install** (`src/runtime.py`): detects `package.json`, `pyproject.toml`, `requirements.txt`, `go.mod` and runs the appropriate install command. Uses content-hash sentinel files at `/data/.install_sentinels/` to skip reinstalls when manifests haven't changed.

**Voice transcription** (`src/transcriber.py`): `Transcriber` ABC with `NullTranscriber` (default, disabled) and `OpenAITranscriber`. `create_transcriber()` factory reads `VoiceConfig`. `WHISPER_API_KEY` falls back to `AI_API_KEY` when `WHISPER_PROVIDER=openai`.

## Key Conventions

- **Adding a new AI backend**: subclass `AICLIBackend`, set `is_stateful`, implement `send()`, add a branch in `factory.py`. Use `SubprocessMixin` if your backend spawns child processes.
- **Tests strip real credentials**: `conftest.py` has an `autouse` fixture that deletes real credential env vars so tests never accidentally hit live services.
- **Test helpers**: use `MagicMock(spec=SettingsSubclass)` and set attributes directly — see `tests/unit/test_bot.py` for the `_make_settings` / `_make_update` pattern.
- **Test layout**: `tests/unit/` — pure logic; `tests/contract/` — verifies all backends satisfy `AICLIBackend`; `tests/integration/` — heavier tests (history DB, factory).
- **`pytest.ini`**: `asyncio_mode = auto`, so all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **Streaming throttle**: Telegram edits during streaming are capped by `BotConfig.stream_throttle_secs` (default `1.0`s), configurable via `STREAM_THROTTLE_SECS` env var.
- **Docker paths**: always use `REPO_DIR` and `DB_PATH` from `src/config.py`; hardcoded to `/repo` and `/data/history.db` in production.
