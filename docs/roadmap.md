# TeleAgent — Roadmap

> Last updated: 2026-03-06

This document tracks pending technical debt, known gaps, and future feature ideas, ordered by priority within each section.

---

## 1. Technical Debt & Fixes

Items ordered: immediate bug → quick wins → medium effort → long-term architecture.

---

### 1.1 Bug — double `@_requires_auth` on `handle_voice`

`bot.py` lines 299–300: the decorator is applied twice to `handle_voice`. Harmless at runtime (PTB's `MessageHandler` bypasses the outer auth check anyway), but incorrect and confusing.

**Fix**: remove the duplicate decorator line. One-line change.

---

### 1.2 Duplication — AI pipeline block copy-pasted in two methods

`bot.py`: the identical 30-line block (history lookup → prompt build → stream/send → history save → error handle → active-task tracking) appears in both `forward_to_ai` and `handle_voice`. Any change must be made twice.

**Fix**: extract `async def _run_ai_pipeline(self, update, text, chat_id)` private method; both handlers delegate to it.

---

### 1.3 Cohesion — `REPO_DIR` defined twice

`runtime.py` line 6 defines `REPO_DIR = Path("/repo")` independently of the same constant already exported from `config.py`. Two sources of truth.

**Fix**: `runtime.py` imports `REPO_DIR` from `src.config` instead of redefining it. Two-line change.

---

### 1.4 Complexity — transcriber init logic inline in `__init__`

`bot.py` lines 104–112: try/except + isinstance check for transcriber setup is buried inside `__init__`, making it hard to unit-test independently.

**Fix**: extract `_init_transcriber(settings) -> Transcriber | None` as a private method.

---

### 1.5 Duplication — provider dispatch repeated in `DirectAPIBackend`

`ai/direct.py`: the `if self._provider in ("openai", ...)` routing appears independently in `send()` and `stream()`. Adding or renaming a provider requires two edits.

**Fix**: extract `_get_provider_callables()` returning `(send_fn, stream_fn)` for the active provider; call once from both public methods.

---

### 1.6 Abstraction — subprocess command building not shared

`ai/session.py` (`_build_cmd`) and `ai/codex.py` (`_make_cmd`) each independently build subprocess command lists and environment dicts with no shared base. Code is similar but diverges silently.

**Fix**: introduce a `SubprocessMixin` in `ai/adapter.py` with a shared `_build_subprocess_env()` utility and consistent interface.

---

### 1.7 Test coverage gaps

CI enforces `--cov-fail-under=70`; current total is **86%** (184 tests). Remaining gaps:

- `bot.py` — `build_app()` handler registration block; streaming error paths; `cmd_info` uptime branches
- `main.py` — clone failure path; SIGTERM teardown; `asyncio.run` exception branch
- `ai/session.py` — `TimeoutError` branch; stdout drain inside stats-marker; `_strip_stats` tail buffer
- `ai/direct.py` — provider-specific streaming branches; stream generator exception handling

---

### 1.8 npm globals not covered by Dependabot

`@github/copilot` and `@openai/codex` are pinned in the Dockerfile but Dependabot does not update npm globals installed via `RUN npm install -g`. Manual update required when new versions ship.

---

### 1.9 Architecture — history storage is not pluggable *(long-term)*

`history.py` is hardcoded to SQLite/aiosqlite. No abstraction exists for alternate storage (Postgres, Redis, file). All callers in `bot.py` would need changing if storage backend changes.

**Fix**: introduce `ConversationStorage` ABC (`add_exchange`, `get_history`, `clear`) with `SQLiteStorage` as the default. Inject via factory.

---

### 1.10 Architecture — `AIConfig` mixes three separate concerns *(long-term)*

`config.py` `AIConfig` contains fields for Copilot, Codex, and Direct API in a flat struct. Adding a new backend adds noise to every other backend's namespace.

**Fix**: split into `CopilotConfig`, `CodexConfig`, `DirectAPIConfig` nested under `AIConfig` with an `ai_cli` discriminator field.

---

## 2. Features

Items ordered by practical value to the typical user.

---

### 2.1 `/ta diff` — show recent git changes

```
/ta diff           → git diff HEAD~1 HEAD (last commit)
/ta diff 3         → git diff HEAD~3 HEAD
/ta diff <sha>     → git diff <sha> HEAD
```

Output truncated and sent as a code block. Pairs well with `/ta sync` after a pull.

---

### 2.2 `/ta log` — tail container logs

```
/ta log            → last 20 lines of the bot's own stdout/stderr
/ta log 50         → last 50 lines
```

Reads from the container's log output. Allows debugging the bot from Telegram without needing SSH access.

---

### 2.3 `/ta schedule` — scheduled commands

Allow recurring shell commands or AI prompts:

```
/ta schedule "git pull && pytest" every 6h
/ta schedule "check if any service is down" every 30m
```

Backed by the existing APScheduler instance already wired in `bot.py`. Schedules stored in `/data/schedules.db` and survive restarts.

---

### 2.4 `/ta switch` — hot-swap AI backend

```
/ta switch copilot
/ta switch codex
/ta switch api
```

`cmd_restart` already re-creates the backend object — this extends it to accept a target backend name. Useful for comparing responses or falling back when one service is down.

---

### 2.5 File upload & download

- **Download**: `/ta file <path>` — send any file from `/repo` as a Telegram document
- **Upload**: accept Telegram document uploads and write them into `/repo/<filename>`

Useful for config edits, log retrieval, or patching files without a full git workflow.

---

### 2.6 Context window control (`HISTORY_TURNS`)

Currently the full SQLite history is injected for stateless backends. Add:

- `HISTORY_TURNS` env var (default: `10`) to cap how many past exchanges are sent
- `/ta context <n>` command to adjust live without restart
- Visible in `/ta info` output

---

### 2.7 Proactive alerts

Let the bot notify the chat proactively when something happens:

- Watch `/repo` for changes to key files (`WATCH_FILES=docker-compose.yml,requirements.txt`)
- Monitor a log file and alert on keywords (`ALERT_KEYWORDS=ERROR,FATAL`)

Uses the existing APScheduler or `watchfiles` library.

---

### 2.8 Voice transcription — local Whisper (offline)

Extend `WHISPER_PROVIDER=local` using the `openai-whisper` Python package:

- Model files **downloaded on first use** (not bundled in Docker image), cached at `WHISPER_MODEL_DIR=/data/whisper-models`
- Model size: `WHISPER_MODEL=tiny|base|small|medium|large` (default: `base`)
- Fully offline, no API key required
- Trade-off: first call slow while model downloads; subsequent calls fast

Implementation: `LocalWhisperTranscriber` in `src/transcriber.py` using `whisper.load_model()`.

---

### 2.9 Voice transcription — Google Speech-to-Text

Extend `WHISPER_PROVIDER=google` using the Google Cloud Speech-to-Text API:

- Requires `google-cloud-speech` package and `GOOGLE_APPLICATION_CREDENTIALS` env var
- Supports wider range of audio formats natively
- Per-minute billing via Google Cloud

Implementation: `GoogleTranscriber` in `src/transcriber.py`.

---

### 2.10 Web dashboard *(optional)*

A lightweight read-only HTTP endpoint (single-file FastAPI) served inside the container:

- Shows uptime, active backend, last 10 exchanges, coverage badge
- Protected by `DASHBOARD_TOKEN` env var
- Exposes `/health` for external monitoring

---

### 2.11 Copilot conversation pre-warming *(low priority)*

Currently `copilot -p` is stateless per call; history is injected from SQLite. A future improvement could pre-warm with a repo-context system prompt to reduce repeated setup overhead for long sessions.
