# TeleAgent — Technical Status & Backlog

> Last updated: 2026-03-05

---

## 1. Project Overview

TeleAgent is a Telegram bot bridge that connects an AI CLI backend (GitHub Copilot, OpenAI Codex, or direct API) to a specific GitHub repository. Each project gets its own Docker container with a dedicated bot.

**Deployment model:** one Docker container per project, all config via env vars.

```
Telegram user
     │  /tarun <cmd> | free text
     ▼
 bot.py (python-telegram-bot)
     │
     ├─ shell commands → executor.py → subprocess in /repo
     ├─ git ops       → repo.py → gitpython
     └─ AI prompts    → ai/factory.py → backend (copilot | codex | api)
                                              │
                                         /repo (cloned GitHub project)
```

---

## 2. Current Architecture

### Source layout

```
src/
├── main.py          # entrypoint: validate env → clone → install deps → start bot
├── config.py        # pydantic-settings models + REPO_DIR / DB_PATH constants
├── bot.py           # Telegram handler class (_BotHandlers) + build_app()
├── executor.py      # shell command runner + output truncation
├── history.py       # aiosqlite conversation store (/data/history.db)
├── repo.py          # git clone, pull, status
├── runtime.py       # auto-detect and install Node/Python/Go deps
└── ai/
    ├── adapter.py   # AICLIBackend ABC (send, stream, clear_history, close, is_stateful)
    ├── factory.py   # create_backend(AIConfig) → concrete backend
    ├── copilot.py   # CopilotBackend — wraps CopilotSession PTY
    ├── session.py   # CopilotSession — pexpect PTY + thread/queue bridge to async
    ├── codex.py     # CodexBackend — asyncio subprocess, streaming via stdout
    └── direct.py    # DirectAPIBackend — OpenAI / Anthropic / Ollama native API
```

### Key design decisions

| Decision | Rationale |
|---|---|
| One container per project | Isolation, independent config, easy to kill/restart per project |
| pexpect PTY for Copilot | Copilot CLI is interactive-only; no programmatic API |
| Thread + SimpleQueue bridge | pexpect is sync; asyncio bridge via daemon thread + `queue.SimpleQueue` polled with `await asyncio.sleep(0.05)` |
| `is_stateful` flag on backends | Copilot (PTY) and DirectAPI manage their own history; Codex is stateless so `history.py` injects past exchanges as context |
| aiosqlite at `/data/history.db` | Persists across restarts via Docker named volume; per `chat_id` isolation |
| `_requires_auth` decorator | Single point of access control; wraps every handler method in `_BotHandlers` |
| `REPO_DIR` / `DB_PATH` in `config.py` | Single source of truth for mount paths; all modules import from here |

### Env var reference (`config.py`)

| Variable | Default | Class |
|---|---|---|
| `BRANCH` | `main` | `GitHubConfig` |
| `AI_CLI` | `copilot` | `AIConfig` |
| `BOT_CMD_PREFIX` | `ta` | `BotConfig` |
| `MAX_OUTPUT_CHARS` | `3000` | `BotConfig` |
| `HISTORY_ENABLED` | `true` | `BotConfig` |
| `STREAM_RESPONSES` | `true` | `BotConfig` |
| `STREAM_THROTTLE_SECS` | `1.0` | `BotConfig` |

### Bot commands (prefix = `ta` by default)

| Command | Handler | Description |
|---|---|---|
| `/tarun <cmd>` | `cmd_run` | Run shell command in `/repo`; destructive cmds require inline confirmation |
| `/tasync` | `cmd_sync` | `git pull` |
| `/tagit` | `cmd_git` | `git status --short -b` + `git log --oneline -3` |
| `/tastatus` | `cmd_status` | List active AI requests with elapsed time |
| `/taclear` | `cmd_clear` | Clear SQLite history + backend in-memory history |
| `/tainfo` | `cmd_info` | Repo, branch, AI backend, uptime, active tasks |
| `/tahelp` | `cmd_help` | Full command reference including app version |
| _any other text_ | `forward_to_ai` | Sent to AI backend; history injected if `!is_stateful` |

---

## 3. CI/CD Pipeline

### Unified workflow (`.github/workflows/ci-cd.yml`)

Single file; all jobs wired with `needs:` + `if:` conditions.

| Job | Runs on | What it does |
|---|---|---|
| `version` | all branches | Reads `VERSION`, builds version string (`X.Y.Z` on main, `X.Y.Z-dev-SHA` on develop) |
| `lint` | all branches | `ruff check src/` |
| `test` | all branches | `pytest` + `--cov=src --cov-fail-under=70` + uploads `coverage.xml` |
| `docker-publish` | `main`, `develop`, `v*` tags | Multi-platform (`amd64` + `arm64`) build → push to `ghcr.io` |
| `security-scan` | after `docker-publish` | Trivy SARIF upload to GitHub Security tab |
| `release` | `main` only, clean semver | Creates GitHub Release with auto-generated changelog |
| `summary` | always | Pipeline outcome table in Actions UI |

### Branch behaviour

| Branch | Docker tags | GitHub Release |
|---|---|---|
| `develop` | `:develop`, `:X.Y.Z-dev-SHA` | Never |
| `main` | `:latest`, `:main`, `:X.Y.Z` | Yes, when `VERSION` is clean semver |
| `v*` tag | `:latest`, `:X.Y.Z` | Yes |

> **`develop` always builds the Docker image** even if lint/tests fail, to catch Dockerfile issues early.
> **`main`** requires lint + tests to pass before building.

### Release flow

1. Work on `develop`; bump `VERSION` before merging
2. `git merge develop main && git push origin main`
3. CI auto-creates `ghcr.io/agigante80/teleagent:X.Y.Z` + GitHub Release

---

## 4. Test Coverage

As of v0.2.0 (134 tests, `pytest-cov>=5.0`):

| Module | Coverage |
|---|---|
| `src/executor.py` | 100% |
| `src/history.py` | 100% |
| `src/repo.py` | 100% |
| `src/runtime.py` | 100% |
| `src/ai/adapter.py` | 100% |
| `src/ai/factory.py` | 100% |
| `src/config.py` | 98% |
| `src/ai/copilot.py` | 90% |
| `src/ai/direct.py` | 80% |
| `src/main.py` | 74% |
| `src/bot.py` | 70% |
| `src/ai/codex.py` | 37% |
| `src/ai/session.py` | 26% |
| **TOTAL** | **71%** |

CI enforces `--cov-fail-under=70`.

---

## 5. Known Gaps & Technical Backlog

---

### 5.1 Test coverage gaps

#### 5.1.1 `ai/session.py` — 26% (highest risk)

`CopilotSession` is the most critical untested module. Every `pexpect` call needs mocking.

**What to cover:**
- `_spawn()` success path: mock `pexpect.spawn`, verify prompt detected
- `_spawn()` auth-failure path: `idx != 0` → `RuntimeError` raised
- `_reader_thread()`: queue receives chunks; sentinel posted on EOF
- `send()` / `stream()`: verify queue is drained into response
- `close()`: child process terminated

**Approach:** `monkeypatch` `pexpect.spawn` with a `MagicMock` that returns controlled `before` bytes.

**File:** `tests/unit/test_session.py` (new)

---

#### 5.1.2 `ai/codex.py` — 37%

`CodexBackend` uses `asyncio.create_subprocess_exec` for streaming. Currently only construction is tested.

**What to cover:**
- `send()`: mock subprocess, verify stdout is accumulated
- `stream()`: mock subprocess yielding chunks, verify async generator output
- Non-zero exit code path → error string returned

**File:** `tests/unit/test_codex_backend.py` (new)

---

#### 5.1.3 `bot.py` — 70%, `main.py` — 74%

Remaining uncovered lines:
- `bot.py:51-71` — `build_app()` function (handler registration)
- `bot.py:147-163` — `cmd_help` (now includes version string)
- `bot.py:167-187` — `cmd_info` (uptime formatting)
- `main.py:73-82` — clone failure path + SIGTERM handler teardown

---

### 5.2 Docker: Go install is architecture-specific

```dockerfile
RUN curl -fsSL https://go.dev/dl/go1.22.4.linux-amd64.tar.gz | tar -C /usr/local -xz
```

This **hardcodes `amd64`** and will **silently fail on `arm64`** (wrong binary). The CI builds `linux/amd64,linux/arm64` so the `arm64` image is currently broken for any Go-dependent runtime.

**Fix:** use `$(dpkg --print-architecture)` to select the right tarball, or use the official `golang` base image in a multi-stage build:

```dockerfile
# Option A — arch-aware download
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://go.dev/dl/go1.22.4.linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
```

---

### 5.3 npm packages not version-pinned

```dockerfile
RUN npm install -g @github/copilot
RUN npm install -g @openai/codex
```

Both install `@latest` on every build. A breaking upstream release silently ships in the next Docker build.

**Fix:** pin to explicit versions:
```dockerfile
RUN npm install -g @github/copilot@1.x @openai/codex@0.x
```
Track updates via Dependabot (already configured for Docker; npm globals are not covered — add a `package.json` with pinned versions if stability is critical).

---

### 5.4 No Docker `HEALTHCHECK`

`docker ps` shows no health status. If the bot crashes silently (e.g. Telegram token invalid), the container stays `Up` with no alert.

**Fix:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"
```

A better check would hit the Telegram `getMe` API endpoint.

---

### 5.5 `runtime.py` reinstalls deps on every container restart

`install_deps()` runs `npm install`, `pip install`, `go mod download` unconditionally at startup. On slow networks this adds 30–120 s to every restart.

**Fix:** cache the result — write a sentinel file after a successful install and skip if it exists (keyed to `requirements.txt` / `package.json` hash).

---

### 5.6 No `/tarestart` command

The only way to restart the AI backend session (e.g. after a Copilot auth refresh) is `docker restart`, which also re-clones the repo.

**Proposed command:** `/tarestart` — calls `backend.close()` then re-initialises via `factory.create_backend()` without restarting the container.

---

## 6. Deployment Notes

### Running locally

```bash
cd /path/to/project-stack
docker compose up -d
docker compose logs -f
```

### Persistent repo (avoid re-cloning on restart)

Mount a local directory as `/repo` in `docker-compose.yml`:

```yaml
volumes:
  - /path/to/local/repo:/repo
```

Omit `GITHUB_REPO` from `.env` when using a bind mount — the clone step is skipped if `/repo/.git` already exists.

### Adding a second project

```bash
mkdir /path/to/another-stack
cp /path/to/project-stack/.env /path/to/another-stack/.env
cp /path/to/project-stack/docker-compose.yml /path/to/another-stack/docker-compose.yml
# Edit .env: new TG_BOT_TOKEN, new GITHUB_REPO
cd /path/to/another-stack && docker compose up -d
```

Each stack is fully independent. Create separate Telegram bots via BotFather (one bot token per project).

---

## 7. Dependency Notes

| Dependency | Version pin | Why |
|---|---|---|
| `python-telegram-bot` | `>=21` | Async-native; `Application` builder pattern |
| `pydantic-settings` | `>=2` | `BaseSettings` with alias support |
| `aiosqlite` | `>=0.20` | Async SQLite for history |
| `pexpect` | `>=4.9` | PTY interaction with Copilot CLI |
| `gitpython` | `>=3.1` | Repo clone/pull |
| `openai` | `>=1.0` | Direct API + streaming |
| `anthropic` | `>=0.28` | Anthropic direct API |
| `ollama` | `>=0.1` | Ollama local API |
| `pytest-cov` | `>=5.0` | Coverage reporting in CI |
| Node.js | LTS (NodeSource) | Required by Copilot CLI and Codex CLI |
| `@github/copilot` (npm) | latest | Copilot CLI — **not** `@githubnext/github-copilot-cli` (deprecated) |
| `@openai/codex` (npm) | latest | OpenAI Codex CLI |
| Go | 1.22.4 | Runtime auto-detection for Go projects |
