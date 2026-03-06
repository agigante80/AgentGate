# TeleAgent — Roadmap

> Last updated: 2026-03-06

This document tracks pending technical work, known gaps, and future feature ideas.
Items are grouped by type — technical debt first, then features.

---

## 1. Technical Debt & Gaps

### 1.1 Test coverage

CI enforces `--cov-fail-under=70`; current total is **86%** (160 tests). Remaining gaps:

#### `bot.py` — 73%, `main.py` — 74%

- `bot.py:52-72` — `build_app()` handler registration block
- `bot.py:169-189` — `cmd_info` uptime formatting branches
- `bot.py:265-282` — streaming error/edge paths
- `main.py:43-45` — clone failure path
- `main.py:73-82` — SIGTERM handler teardown
- `main.py:86` — `asyncio.run` exception branch

#### `ai/session.py` — 90%

- Lines 45–46 — `TimeoutError` path (proc.terminate branch)
- Line 81 — stdout drain inside stats-marker branch
- Lines 88–91 — `_strip_stats` on remaining buffer after loop

#### `ai/direct.py` — 80%

- Lines 54–58, 64–68, 73–74 — provider-specific streaming branches
- Lines 110–117 — exception handling in stream generator

---

### 1.2 npm globals not covered by Dependabot

`@github/copilot` and `@openai/codex` are pinned in the Dockerfile but Dependabot does not update npm globals installed via `RUN npm install -g`. Manual update required when new versions ship.

---

## 2. Feature Ideas

### 2.1 Scheduled commands (`/taschedule`)

Allow users to schedule recurring shell commands or AI prompts:

```
/taschedule "git pull && pytest" every 6h
/taschedule "check if any service is down" every 30m
```

Backed by the existing APScheduler instance already wired in `bot.py`. Schedules stored in `/data/schedules.db` and survive restarts.

---

### 2.2 File upload & download

- **Download**: `/tafile <path>` — send any file from `/repo` as a Telegram document
- **Upload**: accept Telegram document uploads and write them into `/repo/<filename>`

Useful for config file edits, log retrieval, or patching files without a full git workflow.

---

### 2.3 Multi-turn conversation context window control

Currently the full SQLite history is injected for stateless backends. Add:

- `HISTORY_TURNS` env var (default: `10`) to cap how many past exchanges are sent
- `/tacontext <n>` command to change it live without restart
- Visible in `/tainfo` output

---

### 2.4 Proactive alerts

Let the bot notify the chat when something happens in the repo or system without being asked:

- Watch `/repo` for file changes (via `watchfiles` or `inotify`) and notify on changes to key files (e.g. `docker-compose.yml`, `.env.example`)
- Monitor a log file or stdout of a process and alert on keywords (e.g. `ERROR`, `CRITICAL`)
- Example env vars: `WATCH_FILES=docker-compose.yml,requirements.txt`, `ALERT_KEYWORDS=ERROR,FATAL`

---

### 2.5 `/tadiff` — show recent git changes

```
/tadiff           → git diff HEAD~1 HEAD (last commit)
/tadiff 3         → git diff HEAD~3 HEAD
/tadiff <sha>     → git diff <sha> HEAD
```

Output truncated and sent as a code block. Pairs well with `/tasync` after a pull.

---

### 2.6 Inline button confirmations

Replace the current text-based destructive-command confirmation (`/tarun rm -rf ... — confirm? Reply YES`) with Telegram inline buttons (✅ Yes / ❌ No). Cleaner UX, no free-text parsing needed.

Uses `python-telegram-bot`'s `InlineKeyboardMarkup` + `CallbackQueryHandler`.

---

### 2.7 Multi-backend routing

Add a `/taswitch <backend>` command to hot-swap the AI backend:

```
/taswitch copilot
/taswitch codex
/taswitch api
```

`cmd_restart` already re-creates the backend object — this extends it to accept a target backend name. Useful for comparing responses or falling back when one service is down.

---

### 2.8 `/talog` — tail container logs

```
/talog            → last 20 lines of the bot's own stdout/stderr
/talog 50         → last 50 lines
```

Reads from `/proc/1/fd/1` or a log file, so users can debug the bot from within Telegram without SSH access.

---

### 2.9 Web dashboard (optional)

A lightweight read-only HTTP endpoint (FastAPI or Flask, single file) served inside the container:

- Shows uptime, current backend, last 10 exchanges, coverage badge
- Protected by a simple token from env (`DASHBOARD_TOKEN`)
- Exposes `/health` for external monitoring tools

---

### 2.10 Copilot conversation persistence across restarts

Currently `copilot -p` is stateless per call; history is injected from SQLite by the bot. A future improvement could pre-warm a conversation with a system prompt that provides repo context, reducing repeated setup overhead for long sessions.

---

### 2.11 Voice transcription — local Whisper (offline)

Extend `WHISPER_PROVIDER=local` to use the `openai-whisper` Python package running on the local machine:

- Model files are **downloaded on first use** (not bundled in the Docker image) and cached at `WHISPER_MODEL_DIR=/data/whisper-models`
- Model size configurable via `WHISPER_MODEL=tiny|base|small|medium|large` (default: `base`)
- No API key required; runs fully offline
- Trade-off: first transcription is slow while the model downloads; subsequent calls are fast

Implementation: `LocalWhisperTranscriber` in `src/transcriber.py` using `whisper.load_model()`.

---

### 2.12 Voice transcription — Google Speech-to-Text

Extend `WHISPER_PROVIDER=google` to use the Google Cloud Speech-to-Text API:

- Requires `google-cloud-speech` package and `GOOGLE_APPLICATION_CREDENTIALS` env var pointing to a service account JSON
- Supports a wider range of audio formats natively
- Per-minute billing via Google Cloud

Implementation: `GoogleTranscriber` in `src/transcriber.py` using `google.cloud.speech.SpeechAsyncClient`.
