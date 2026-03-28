# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

**Owner**: `agigante80` | **Repo**: `agigante80/AgentGate` | **Branches**: `main` (production), `develop` (active development)

## Commands

```bash
# Lint
ruff check src/

# Lint docs (checks env var coverage in README, .env.example, docker-compose.yml.example)
python scripts/lint_docs.py

# Run all tests
pytest tests/ -v --tb=short

# Single test file
pytest tests/unit/test_bot.py -v

# Single test
pytest tests/unit/test_bot.py::TestPrefix::test_default_prefix -v

# Coverage
pytest tests/ --cov=src --cov-report=term-missing

# Run locally
pip install -r requirements.txt && pip install -r requirements-dev.txt
python -m src.main
```

## Architecture

AgentGate is an async Python 3.12+ bot (Telegram or Slack) that acts as a gateway to pluggable AI backends. Each deployment is one Docker container per project repo.

### Startup flow (`src/main.py`)

Validate config -> clone GitHub repo -> auto-install deps -> init SQLite history/audit DBs -> build `Services` dataclass -> create AI backend -> start bot -> send Ready message -> write `/tmp/healthy`.

### Config (`src/config.py`)

Pydantic `BaseSettings` split into sub-configs: `TelegramConfig`, `SlackConfig`, `GitHubConfig`, `AIConfig`, `BotConfig`, `VoiceConfig`, `StorageConfig`, `LogConfig`. All values from env vars. Every sub-config implements `secret_values() -> list[str]` for dynamic secret redaction (`SecretProvider` protocol -- add this method to any new sub-config). Module-level `REPO_DIR` and `DB_PATH` constants -- always import these instead of hardcoding paths.

### AI backends (`src/ai/`)

- **`adapter.py`**: `AICLIBackend` ABC with `send()`, `stream()`, `clear_history()`, `close()`, and `is_stateful` flag. `SubprocessMixin` for backends that spawn child processes in `REPO_DIR`.
- **Stateless** (history injected via `build_prompt()`): `CopilotBackend`, `CodexBackend`, `GeminiBackend`, `ClaudeBackend`
- **Stateful** (maintains native message list): `DirectAPIBackend` (OpenAI/Anthropic/Ollama). Reads `SYSTEM_PROMPT` or `SYSTEM_PROMPT_FILE` for system message.
- **`factory.py`**: Selects backend via `AI_CLI` env var (`copilot` | `codex` | `api` | `gemini` | `claude`). Backends registered with `@backend_registry.register("key")` and lazy-loaded via `_load_backends()`.
- **Stateful vs stateless**: if `backend.is_stateful` is `True`, raw prompt is sent directly. If `False`, last `HISTORY_TURNS` (default 10) exchanges are prepended via `history.build_context()`.

### Platform layer (`src/platform/`)

- `common.py`: Shared helpers -- `build_prompt()`, `save_to_history()`, `thinking_ticker()`, `split_text()`, `is_allowed_slack()`
- `bot.py`: Telegram bot with `@_requires_auth` decorator on all handlers. Streaming edits throttled by `STREAM_THROTTLE_SECS` (default 1.0s).
- `slack.py`: Slack bot using `slack-bolt[async]` Socket Mode. Supports multi-agent features (`TRUSTED_AGENT_BOT_IDS`), delegation blocks (`[DELEGATE: ...]`), Block Kit thinking placeholders, and thread replies (`SLACK_THREAD_REPLIES`)

Platform selected by `PLATFORM` env var (default `telegram`).

### Registry system (`src/registry.py`)

Generic `Registry[T]` with four instances: `backend_registry`, `platform_registry`, `storage_registry`, `audit_registry`. Register with `@registry.register("key")`, instantiate with `registry.create("key", ...)`. Loaded lazily via `_load_backends()` / `_load_platforms()` -- import-safe, fork-safe.

### Module loading (`src/_loader.py`)

`_module_file_exists(dotted_name) -> bool` -- fork-safe existence check using `importlib.util.find_spec`. Used by `_load_backends()` and `_load_platforms()` to skip missing optional modules without bare `try/except ImportError`.

### Command registry (`src/commands/registry.py`)

`@register_command(name, help)` decorator. `_validate_command_symmetry()` asserts every Telegram command has a Slack mirror -- CI fails if one platform is missing.

### Other key modules

- **`executor.py`**: `run_shell()` runs in `REPO_DIR`, `is_destructive()` keyword-checks, `sanitize_git_ref()` validates user input before git commands. `summarize_if_long()` wraps content in `<OUTPUT>` tags for prompt injection hardening.
- **`redact.py`**: `SecretRedactor` scrubs outgoing text of known tokens/patterns (GitHub PATs, Slack tokens, OpenAI keys, Bearer headers, URLs with credentials). Set `ALLOW_SECRETS=true` to disable.
- **`history.py`**: `ConversationStorage` ABC with `SQLiteStorage` and `InMemoryStorage`. `build_context()` prepends history for stateless backends. `HISTORY_TURNS` controls injection count (default 10). Backend selected via `STORAGE_BACKEND` env var (`sqlite` or `memory`).
- **`audit.py`**: `AuditLog` ABC with `SQLiteAuditLog` and `NullAuditLog`. Exception-swallowing design. Callers must redact before recording. `verify()` smoke-tests write->read at startup. Backend selected via `AUDIT_BACKEND` (`sqlite` or `null` when `AUDIT_ENABLED=false`).
- **`services.py`**: `Services` dataclass bundles `ShellService`, `RepoService` (or `NullRepoService`), `SecretRedactor`, and optional `Transcriber`. Constructed once in `main.py`. `AuditLog` is passed separately to bot constructors.
- **`runtime.py`**: Auto-detects and installs deps from `package.json`/`pyproject.toml`/`requirements.txt`/`go.mod`. Content-hash sentinel files at `/data/.install_sentinels/` skip reinstalls when manifests haven't changed.
- **`ready_msg.py`**: `build_ready_message()` and `ai_label()` -- generates startup status message for both platforms.
- **`logging_setup.py`**: `configure_logging()` -- rotating file logs with daily rotation, 14-day retention, gzip compression.
- **`repo.py`**: Git operations (clone, pull, status, auth) used during startup and by bot commands.
- **`transcriber.py`**: `Transcriber` ABC with `OpenAITranscriber` and `NullTranscriber`. Voice message support via `VOICE_PROVIDER` env var. `WHISPER_API_KEY` required when `WHISPER_PROVIDER=openai`.

### Skills / agent personas (`skills/`)

Markdown files defining specialized agent roles (`dev-agent.md`, `docs-agent.md`, `sec-agent.md`). Loaded via `SYSTEM_PROMPT_FILE` or `COPILOT_SKILLS_DIRS`. `SYSTEM_PROMPT_FILE` must NOT point inside `REPO_DIR` (enforced in `factory.py`) -- mount via separate Docker volume.

### Docs (`docs/`)

`docs/guides/` has practical how-to guides (Slack setup, multi-agent, logging, versioning). `lint_docs.py` enforces env var documentation sync between `src/config.py`, `README.md`, `.env.example`, and `docker-compose.yml.example`.

## Key Conventions

- **Secret redaction**: Always pass `SecretRedactor` to `run_shell()` and call `redactor.redact()` on any text going back to users.
- **Git ref safety**: Always use `executor.sanitize_git_ref(ref)` before interpolating user input into git commands.
- **Adding an AI backend**: Subclass `AICLIBackend`, set `is_stateful`, implement `send()`. Override `stream()` for true streaming, `close()` if holding a process. Decorate with `@backend_registry.register("key")`, add to `_load_backends()` in `factory.py`. Use `SubprocessMixin` if spawning child processes.
- **New config values**: Add to appropriate sub-config in `src/config.py`. Must implement `secret_values()`. Update `.env.example` and `README.md` -- `lint_docs.py` enforces this.
- **New bot commands**: Implement `cmd_<name>` in both `bot.py` and `slack.py` with `@register_command()`. Symmetry is enforced by CI.
- **Auth guards**: Telegram handlers use `@_requires_auth`. Slack handlers call `self._is_allowed()` early.
- **Docker paths**: Always use `REPO_DIR` and `DB_PATH` from `src/config.py`.
- **System prompt file**: `SYSTEM_PROMPT_FILE` must NOT point inside `REPO_DIR` (enforced in `factory.py`).

## Testing

- **`pytest.ini`**: `asyncio_mode = auto` -- no `@pytest.mark.asyncio` needed on async tests.
- **`conftest.py`**: Autouse fixture strips real credentials so tests never hit live services.
- **Layout**: `tests/unit/` (pure logic), `tests/contract/` (backend interface compliance), `tests/integration/` (history DB, factory).
- **Fixtures**: Use `MagicMock(spec=SettingsSubclass)` with direct attribute setting. See `_make_settings()` / `_make_update()` patterns in test files.

## CI/CD (`.github/workflows/ci-cd.yml`)

Single pipeline: `version` -> `lint` + `test` (parallel) -> `docker-publish` + `security-scan` -> `release` -> `summary`. On `develop`: publishes `:develop` Docker tag. On `main`: version-bump check (VERSION file must be bumped), publishes `:latest`, creates GitHub Release. Multi-platform builds (amd64 + arm64). `workflow_dispatch` supports `skip_tests` and `skip_docker_publish` inputs for emergency deployments.

## Common Extension Patterns

### Adding a config field
```python
# src/config.py -- add to the appropriate sub-config
class BotConfig(BaseSettings):
    my_new_setting: bool = False  # MY_NEW_SETTING env var
```

### Adding a new AI backend
```python
# src/ai/my_backend.py
from src.ai.adapter import AICLIBackend
from src.registry import backend_registry

@backend_registry.register("mybackend")
class MyBackend(AICLIBackend):
    is_stateful = True  # or False if the bot provides history via context injection

    async def send(self, prompt: str) -> str: ...
    def clear_history(self) -> None: ...
    def close(self) -> None: ...  # if holding a subprocess/PTY

# src/ai/factory.py -- add to _load_backends():
_module_file_exists("src.ai.my_backend") and __import__("src.ai.my_backend")
```

### Adding a new sub-config with secrets
```python
# src/config.py
class MyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    my_token: str = Field("", env="MY_TOKEN")

    def secret_values(self) -> list[str]:
        return [v for v in [self.my_token] if v]

# Add to Settings:
class Settings(BaseSettings):
    my: MyConfig = MyConfig()
```

### Test pattern
```python
from unittest.mock import MagicMock
from src.config import Settings, BotConfig

def _make_settings(**overrides):
    s = MagicMock(spec=Settings)
    s.bot = MagicMock(spec=BotConfig)
    s.bot.my_setting = overrides.get("my_setting", False)
    return s
```
