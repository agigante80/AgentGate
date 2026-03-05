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

TeleAgent is an async Python Telegram bot that acts as a gateway to pluggable AI backends. Each deployment is one Docker container per project repo.

**Startup flow** (`src/main.py`): validate config → clone GitHub repo → auto-install deps → init SQLite history DB → create AI backend → start Telegram bot → send 🟢 Ready.

**Config** (`src/config.py`): Pydantic `BaseSettings` split into four sub-configs (`TelegramConfig`, `GitHubConfig`, `BotConfig`, `AIConfig`). All settings come from env vars. `Settings.load()` constructs them and is the only entry point.

**AI backend abstraction** (`src/ai/`):
- `adapter.py` defines the `AICLIBackend` ABC: `send()`, `stream()`, `clear_history()`, and the `is_stateful` class-level flag.
- `factory.py` selects the concrete backend based on the `AI_CLI` env var (`copilot` | `codex` | `api`).
- `copilot.py` — stateful PTY session via `pexpect`; manages its own conversation state.
- `codex.py` — stateful Codex CLI backend.
- `direct.py` — stateless `DirectAPIBackend` for OpenAI / Anthropic / Ollama.

**Stateful vs stateless backends** (`src/bot.py → forward_to_ai`): if `backend.is_stateful` is `True`, the raw prompt is sent directly. If `False`, the last 10 history exchanges from SQLite are prepended via `history.build_context()` before sending.

**Bot handlers** (`src/bot.py`): all Telegram handlers live in `_BotHandlers`. Every handler method is guarded by `@_requires_auth` (checks `TG_CHAT_ID` and optional `ALLOWED_USERS`). Utility commands use the configurable prefix (default `ta`); everything else is forwarded to the AI.

**CI/CD** (`.github/workflows/ci-cd.yml`): single unified pipeline. Jobs: `version` → `lint` + `test` (parallel) → `docker-publish` + `security-scan` → `release` → `summary`. On `develop`: publishes `:develop` Docker tag. On `main`: version-bump check, publishes `:latest`, creates a GitHub Release. Multi-platform builds (amd64 + arm64). `workflow_dispatch` supports `skip_tests` and `skip_docker_publish` inputs.

**History** (`src/history.py`): async SQLite at `/data/history.db`. Stores up to 10 exchanges per `chat_id`. Only used by stateless backends; stateful backends track context themselves.

## Key Conventions

- **Adding a new AI backend**: subclass `AICLIBackend`, set `is_stateful`, implement `send()`, add a branch in `factory.py`.
- **Tests strip real credentials**: `conftest.py` has an `autouse` fixture that deletes real credential env vars so tests never accidentally hit live services.
- **Test helpers**: use `MagicMock(spec=SettingsSubclass)` and set attributes directly — see `tests/unit/test_bot.py` for the `_make_settings` / `_make_update` pattern.
- **Test layout**: `tests/unit/` — pure logic; `tests/contract/` — verifies all backends satisfy `AICLIBackend`; `tests/integration/` — heavier tests (history DB, factory).
- **`pytest.ini`**: `asyncio_mode = auto`, so all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **Streaming throttle**: Telegram edits during streaming are capped at 1 edit/second (`_THROTTLE = 1.0` in `bot.py`) to avoid rate-limit errors.
- **Docker paths**: repo is always at `/repo`; history DB at `/data/history.db`. These are hardcoded, not configurable.
