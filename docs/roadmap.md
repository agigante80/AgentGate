# AgentGate — Roadmap

> Last updated: 2026-03-07

This document tracks pending technical debt, known gaps, and future feature ideas, ordered by priority within each section.

---

## 1. Technical Debt & Fixes

Items ordered: quick wins → medium effort → long-term architecture.

---

### 1.1 Test coverage gaps

CI enforces `--cov-fail-under=70`; current total is **86%** (194 tests). Remaining gaps:

- `bot.py` — `build_app()` handler registration block; streaming error paths; `cmd_info` uptime branches
- `main.py` — clone failure path; SIGTERM teardown; `asyncio.run` exception branch
- `ai/session.py` — `TimeoutError` branch; stdout drain inside stats-marker; `_strip_stats` tail buffer
- `ai/direct.py` — provider-specific streaming branches; stream generator exception handling

---

### 1.2 npm globals not covered by Dependabot

`@github/copilot` and `@openai/codex` are pinned in the Dockerfile but Dependabot does not update npm globals installed via `RUN npm install -g`. Manual update required when new versions ship.

---

### 1.3 Architecture — history storage is not pluggable *(long-term)*

`history.py` is hardcoded to SQLite/aiosqlite. No abstraction exists for alternate storage (Postgres, Redis, file). All callers in `bot.py` would need changing if storage backend changes.

**Fix**: introduce `ConversationStorage` ABC (`add_exchange`, `get_history`, `clear`) with `SQLiteStorage` as the default. Inject via factory.

---

### 1.4 Architecture — `AIConfig` mixes three separate concerns *(long-term)*

`config.py` `AIConfig` contains fields for Copilot, Codex, and Direct API in a flat struct. Adding a new backend adds noise to every other backend's namespace.

**Fix**: split into `CopilotConfig`, `CodexConfig`, `DirectAPIConfig` nested under `AIConfig` with an `ai_cli` discriminator field.

---

## 2. Features

Items ordered by practical value to the typical user.

---

### 2.0 Multi-platform messaging — Slack + Telegram *(medium)*

Add Slack as an optional front-end alongside Telegram, chosen via `PLATFORM=telegram|slack`.

**Design**: `MessagingAdapter` ABC in `src/platform/adapter.py`; `TelegramAdapter` (extracted from `bot.py`) and `SlackAdapter` (`slack-bolt[async]`, Socket Mode) both implement it. All AI, history, executor, and repo logic is already platform-agnostic and needs zero changes.

**Key decisions documented in**: `docs/features/multi-platform-messaging.md`

Notable challenges: Slack slash command registration (manual, one-time), Socket Mode requiring two tokens (`SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`), and `mrkdwn` vs Telegram Markdown formatting.

**Also consider renaming the project** since it will no longer be Telegram-only. Candidates in the feature doc: AgentGate, BotBridge, DevRelay, MeshAgent, CliMesh.

---

### 2.1 `/ta schedule` — scheduled commands

Allow recurring shell commands or AI prompts:

```
/ta schedule "git pull && pytest" every 6h
/ta schedule "check if any service is down" every 30m
```

Requires adding `APScheduler` as a dependency. Schedules stored in `/data/schedules.db` and survive restarts.

---

### 2.2 `/ta switch` — hot-swap AI backend

```
/ta switch copilot
/ta switch codex
/ta switch api
```

`cmd_restart` already re-creates the backend object — this extends it to accept a target backend name. Useful for comparing responses or falling back when one service is down.

---

### 2.3 File upload & download

- **Download**: `/ta file <path>` — send any file from `/repo` as a Telegram document
- **Upload**: accept Telegram document uploads and write them into `/repo/<filename>`

Useful for config edits, log retrieval, or patching files without a full git workflow.

---

### 2.4 Context window control (`HISTORY_TURNS`)

Currently the full SQLite history is injected for stateless backends. Add:

- `HISTORY_TURNS` env var (default: `10`) to cap how many past exchanges are sent
- `/ta context <n>` command to adjust live without restart
- Visible in `/ta info` output

---

### 2.5 Proactive alerts

Let the bot notify the chat proactively when something happens:

- Watch `/repo` for changes to key files (`WATCH_FILES=docker-compose.yml,requirements.txt`)
- Monitor a log file and alert on keywords (`ALERT_KEYWORDS=ERROR,FATAL`)

Uses the existing APScheduler or `watchfiles` library.

---

### 2.6 Voice transcription — local Whisper (offline)

Extend `WHISPER_PROVIDER=local` using the `openai-whisper` Python package:

- Model files **downloaded on first use** (not bundled in Docker image), cached at `WHISPER_MODEL_DIR=/data/whisper-models`
- Model size: `WHISPER_MODEL=tiny|base|small|medium|large` (default: `base`)
- Fully offline, no API key required
- Trade-off: first call slow while model downloads; subsequent calls fast

Implementation: `LocalWhisperTranscriber` in `src/transcriber.py` using `whisper.load_model()`.

---

### 2.7 Voice transcription — Google Speech-to-Text

Extend `WHISPER_PROVIDER=google` using the Google Cloud Speech-to-Text API:

- Requires `google-cloud-speech` package and `GOOGLE_APPLICATION_CREDENTIALS` env var
- Supports wider range of audio formats natively
- Per-minute billing via Google Cloud

Implementation: `GoogleTranscriber` in `src/transcriber.py`.

---

### 2.8 Web dashboard *(optional)*

A lightweight read-only HTTP endpoint (single-file FastAPI) served inside the container:

- Shows uptime, active backend, last 10 exchanges, coverage badge
- Protected by `DASHBOARD_TOKEN` env var
- Exposes `/health` for external monitoring

---

### 2.9 Copilot conversation pre-warming *(low priority)*

Currently `copilot -p` is stateless per call; history is injected from SQLite. A future improvement could pre-warm with a repo-context system prompt to reduce repeated setup overhead for long sessions.
