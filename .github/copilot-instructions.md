# Copilot Instructions

## Repository Identity

**GitHub owner**: `agigante80`
**Repository**: `agigante80/AgentGate`
**Default branch**: `main` (production) | `develop` (active development)

When using GitHub MCP tools, always use `owner: "agigante80"` and `repo: "AgentGate"`.

## Commands

```bash
# Lint
ruff check src/

# Lint docs (checks README config coverage, .env.example, docker-compose.yml.example)
python scripts/lint_docs.py

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

AgentGate is an async Python bot (Telegram **or** Slack) that acts as a gateway to pluggable AI backends. Each deployment is one Docker container per project repo.

**Startup flow** (`src/main.py`): validate config → clone GitHub repo → auto-install deps → init SQLite history DB → init audit log → build `Services` dataclass → create AI backend → start bot (Telegram or Slack) → send 🟢 Ready. Storage and audit backends are selected via `storage_registry.create(settings.storage.storage_backend)` and `audit_registry.create(settings.storage.audit_backend)`.

**Config** (`src/config.py`): Pydantic `BaseSettings` split into six sub-configs (`TelegramConfig`, `SlackConfig`, `GitHubConfig`, `BotConfig`, `AIConfig`, `VoiceConfig`). All settings come from env vars. `Settings.load()` constructs them and is the only entry point. `TelegramConfig` fields are optional (default `""`) — validation that they're present happens in `_validate_config()` in `main.py`. Module-level `REPO_DIR` and `DB_PATH` constants are defined here — always import these instead of hardcoding `/repo` or `/data`.

**Platform abstraction** (`src/platform/`):
- `common.py` — shared helpers used by both bots: `build_prompt()` (injects history for stateless backends), `save_to_history()`, `is_allowed_slack()`, `thinking_ticker()` (async background task that edits the "Thinking…" message with elapsed time; started by both bots during `_run_ai_pipeline()`).
- `slack.py` — `SlackBot` class using `slack-bolt[async]` in Socket Mode. Message events with prefix parsing (e.g. `gate run`, `gate sync`). Streaming via `client.chat_update(ts=…)`. Confirmation dialogs via Block Kit Actions. Voice via file download with auth header.

**Bot handlers** (`src/bot.py`): all Telegram handlers live in `_BotHandlers`. Constructor signature: `_BotHandlers(settings, backend, storage, start_time, audit)`. Every handler method is guarded by `@_requires_auth` (checks `TG_CHAT_ID` and optional `ALLOWED_USERS`). Utility commands use the configurable prefix (default `gate`); everything else is forwarded to the AI.

**Platform selection**: `PLATFORM=telegram` (default) uses `src/bot.py`; `PLATFORM=slack` uses `src/platform/slack.py::SlackBot`. Both call the same AI backends, history, executor, and repo modules.
- `adapter.py` defines the `AICLIBackend` ABC: `send()`, `stream()` (yields chunks; default yields `send()` at once), `clear_history()`, `close()` (release PTY/process resources), and the `is_stateful` class-level flag. Also defines `SubprocessMixin` for backends that spawn child processes in `REPO_DIR`.
- `factory.py` selects the concrete backend based on the `AI_CLI` env var (`copilot` | `codex` | `api`).
- `copilot.py` + `session.py` — **stateless** `CopilotBackend` (`is_stateful = False`). `CopilotSession` spawns `copilot -p <prompt> --allow-all` as a subprocess; the bot provides history via context injection. `COPILOT_SKILLS_DIRS` passes extra skills directories to the CLI.
- `codex.py` — **stateless per-invocation** `CodexBackend` (`is_stateful = False`). Spawns `codex <prompt> --approval-mode full-auto --model <model>` as a subprocess. Each AgentGate message is a fresh Codex process; conversation history is injected by `build_prompt()`. Codex handles multi-step agentic execution within the single call (file edits, shell commands, tool use). Default model: `gpt-5.3-codex`.
- `direct.py` — **stateful** `DirectAPIBackend` (`is_stateful = True`) for OpenAI / Anthropic / Ollama. Maintains a `self._messages` list natively. Reads `SYSTEM_PROMPT` (inline text) or `SYSTEM_PROMPT_FILE` (path to a markdown file) to prepend a system message.
- `gemini.py` — **stateless** `GeminiBackend` (`is_stateful = False`). Spawns `gemini -p <prompt> --yolo -o text` as a subprocess. Requires `GEMINI_API_KEY`. `--yolo` auto-approves all tool calls (file ops + shell execution); Docker container isolation is the containment boundary. `-o text` prevents ANSI/JSON decorations in captured output. `--approval-mode` is stripped from `AI_CLI_OPTS` to prevent conflicting with `--yolo`.

**Stateful vs stateless backends** (`src/bot.py → forward_to_ai`): if `backend.is_stateful` is `True`, the raw prompt is sent directly. If `False`, the last `HISTORY_TURNS` (default `10`) history exchanges from SQLite are prepended via `history.build_context()` before sending. Set `HISTORY_TURNS=0` to disable injection only (history is still stored).

**CI/CD** (`.github/workflows/ci-cd.yml`): single unified pipeline. Jobs: `version` → `lint` + `test` (parallel) → `docker-publish` + `security-scan` → `release` → `summary`. On `develop`: publishes `:develop` Docker tag. On `main`: version-bump check, publishes `:latest`, creates a GitHub Release. Multi-platform builds (amd64 + arm64). `workflow_dispatch` supports `skip_tests` and `skip_docker_publish` inputs.

**Audit log** (`src/audit.py`): `AuditLog` ABC with `SQLiteAuditLog` (writes to `AUDIT_DB_PATH = /data/audit.db`) and `NullAuditLog` (no-op). Constructed in `main.py` based on `AUDIT_ENABLED` (default `true`) and injected into `_BotHandlers` and `SlackBot`. Design mirrors `history.py` — ABC + SQLite, async-first, exception-swallowing. **Callers must redact sensitive data before calling `audit.record()`**. Records platform, chat_id, user_id, action, detail, status, and duration_ms.

**History** (`src/history.py`): `ConversationStorage` ABC with `SQLiteStorage` concrete implementation (async SQLite at `/data/history.db`). `SQLiteStorage` is constructed in `main.py` (`SQLiteStorage(DB_PATH)`, `await storage.init()`) and injected into `_BotHandlers` and `SlackBot` constructors. `build_context()` remains a module-level pure function. Stores exchanges per `chat_id`; the number injected per prompt is controlled by `HISTORY_TURNS` (default `10`). Only used by stateless backends; stateful backends track context themselves.

**Registry** (`src/registry.py`): `Registry[T]` generic class. Four module-level instances: `backend_registry` (AI backends), `platform_registry` (bot platforms), `storage_registry` (history storage), `audit_registry` (audit log). Use `@registry.register("key")` to register; use `registry.create("key", ...)` to instantiate. Registries are loaded lazily via `_load_backends()` / `_load_platforms()` in `factory.py` and `main.py` — import-safe, fork-safe.

**Services** (`src/services.py`): `Services` dataclass bundles `shell: ShellService`, `repo: RepoService | NullRepoService`, and `audit: AuditLog` for injection into `_BotHandlers` and `SlackBot`. `RepoService` wraps `REPO_DIR`; `NullRepoService` is the no-op fallback. Construct once in `main.py` and pass to the bot constructor — do not re-construct per request.

**Command registry** (`src/commands/registry.py`): `CommandDef` datatype + `register_command(name, help)` decorator. Registers handler methods into the module-level `COMMANDS` dict. Raises `ValueError` on duplicate `name` (idempotent on hot-reload). `_validate_command_symmetry()` asserts every Telegram command has a Slack mirror. All `cmd_*` methods in `bot.py` and `slack.py` use `@register_command`.

**`SecretProvider` protocol** (`src/config.py`): each sub-config class (`TelegramConfig`, `SlackConfig`, `GitHubConfig`, `BotConfig`, `AIConfig`, `VoiceConfig`, `StorageConfig`) implements `secret_values() -> list[str]` returning its live secret strings. `SecretRedactor._collect_secrets()` iterates sub-configs via protocol duck-typing — add `secret_values()` to any new sub-config. `StorageConfig` holds `STORAGE_BACKEND` and `AUDIT_BACKEND` (default `"sqlite"`/`"sqlite"`).

**`_loader.py`** (`src/_loader.py`): `_module_file_exists(dotted_name) -> bool` — fork-safe existence check using `importlib.util.find_spec`. Used by `_load_backends()` and `_load_platforms()` to skip missing optional modules without bare `try/except ImportError`.

**Secret redaction** (`src/redact.py`): `SecretRedactor` is instantiated in both `_BotHandlers` and `SlackBot` at startup. It scrubs outgoing text (AI responses, shell output, error messages) of known token values collected from `Settings` and common secret patterns (GitHub PATs, Slack tokens, OpenAI keys, Bearer headers, URLs with embedded credentials). Set `ALLOW_SECRETS=true` to disable. Always pass the redactor to `run_shell()` and apply `redactor.redact()` to any text sent back to the user.

**Shell execution** (`src/executor.py`): `run_shell(cmd, max_chars, redactor=None)` runs commands in `REPO_DIR`, appends `[exit N]`, and truncates long output. `is_destructive()` keyword-checks commands; `is_exempt()` checks against `BotConfig.skip_confirm_keywords`. `summarize_if_long()` wraps content in `<OUTPUT>` tags before sending to the AI (prompt injection hardening). `sanitize_git_ref(ref)` validates user-supplied git refs against an allowlist pattern and returns a shell-quoted string or `None` — always use this before interpolating user input into git commands.

**Dependency auto-install** (`src/runtime.py`): detects `package.json`, `pyproject.toml`, `requirements.txt`, `go.mod` and runs the appropriate install command. Uses content-hash sentinel files at `/data/.install_sentinels/` to skip reinstalls when manifests haven't changed.

**Voice transcription** (`src/transcriber.py`): `Transcriber` ABC with `NullTranscriber` (default, disabled) and `OpenAITranscriber`. `create_transcriber()` factory reads `VoiceConfig`. `WHISPER_API_KEY` is required (no fallback) when `WHISPER_PROVIDER=openai`; `AI_API_KEY` is no longer accepted as a substitute (removed in v1.1.0).

**Skills / agent personas** (`skills/`): markdown files that define specialized agent roles (`dev-agent.md`, `docs-agent.md`, `sec-agent.md`). Loaded via `SYSTEM_PROMPT_FILE` or `COPILOT_SKILLS_DIRS`. `SYSTEM_PROMPT_FILE` must **not** point inside `REPO_DIR` (enforced at startup in `factory.py`) — mount it via a separate Docker volume. `TRUSTED_AGENT_BOT_IDS` lists Slack bot IDs (or `Name:prefix` pairs) that bypass the normal user filter for agent-to-agent messaging.

**Docs** (`docs/`): `docs/guides/` — practical how-to guides. Feature planning and prioritization lives in GitHub Issues (`type:feature` + `status:*` + `priority:*` labels). `lint_docs.py` enforces: every env var in `src/config.py` is documented in `README.md`; `.env.example` and `docker-compose.yml.example` have no stale entries.

## Key Conventions

- **Secret redaction**: always pass the `SecretRedactor` instance to `run_shell()` and call `redactor.redact()` on any text going back to the user — AI responses, error messages, shell output. New bot/Slack handlers must follow the same pattern as existing ones in `bot.py` / `slack.py`.
- **Git ref safety**: use `executor.sanitize_git_ref(ref)` before interpolating any user-supplied string into a git command. It returns `None` for invalid refs.
- **Adding a new AI backend**: subclass `AICLIBackend`, set `is_stateful`, implement `send()`. Override `stream()` for true streaming, `close()` if the backend holds a long-lived process. Decorate with `@backend_registry.register("key")` and add to `_load_backends()` in `factory.py`. Use `SubprocessMixin` if spawning child processes.
- **New config values go in the appropriate sub-config** in `src/config.py` (`BotConfig`, `AIConfig`, `SlackConfig`, `StorageConfig`, etc.). All values come from env vars via Pydantic `BaseSettings`. Every sub-config must implement `secret_values() -> list[str]` (return live secret strings; empty list if none).
- **Adding a new bot command**: implement `cmd_<name>` in both `bot.py` and `slack.py`, decorate both with `@register_command("name", help="…")`. `_validate_command_symmetry()` will fail CI if one platform is missing.
- **Auth guards**: every Telegram handler must be wrapped with `@_requires_auth`. Every Slack handler must call `self._is_allowed(channel, user)` early.
- **Tests strip real credentials**: `conftest.py` has an `autouse` fixture that deletes real credential env vars so tests never accidentally hit live services.
- **Test helpers**: use `MagicMock(spec=SettingsSubclass)` and set attributes directly — see `tests/unit/test_bot.py` for the `_make_settings` / `_make_update` pattern.
- **Test layout**: `tests/unit/` — pure logic; `tests/contract/` — verifies all backends satisfy `AICLIBackend`; `tests/integration/` — heavier tests (history DB, factory).
- **`pytest.ini`**: `asyncio_mode = auto`, so all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **Streaming throttle**: Telegram edits during streaming are capped by `BotConfig.stream_throttle_secs` (default `1.0`s), configurable via `STREAM_THROTTLE_SECS` env var.
- **Docker paths**: always use `REPO_DIR` and `DB_PATH` from `src/config.py`; hardcoded to `/repo` and `/data/history.db` in production.

## Common Extension Patterns

### Adding a config field
```python
# src/config.py — add to the appropriate sub-config
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

# src/ai/factory.py — add to _load_backends():
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
