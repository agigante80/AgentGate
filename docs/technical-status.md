# TeleAgent — Technical Status & Backlog

> Last updated: 2026-03-05
> Coverage: **46%** (98 tests passing)

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
├── config.py        # pydantic-settings models (all env vars)
├── bot.py           # Telegram handler class (_BotHandlers) + build_app()
├── executor.py      # shell command runner + truncation/summarization
├── history.py       # aiosqlite conversation store (/data/history.db)
├── repo.py          # git clone, pull, status
├── runtime.py       # auto-detect and install Node/Python/Go deps
└── ai/
    ├── adapter.py   # AICLIBackend ABC (send, stream, clear_history, is_stateful)
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

### Env var defaults (set in `config.py`, no `.env` required)

| Variable | Default | Class |
|---|---|---|
| `BRANCH` | `main` | `GitHubConfig` |
| `AI_CLI` | `copilot` | `AIConfig` |
| `BOT_CMD_PREFIX` | `ta` | `BotConfig` |
| `MAX_OUTPUT_CHARS` | `3000` | `BotConfig` |
| `HISTORY_ENABLED` | `true` | `BotConfig` |
| `STREAM_RESPONSES` | `true` | `BotConfig` |

### Bot commands (prefix = `ta` by default)

| Command | Handler | Description |
|---|---|---|
| `/tarun <cmd>` | `cmd_run` | Run shell command in `/repo`; destructive cmds require inline confirmation |
| `/tasync` | `cmd_sync` | `git pull` |
| `/tagit` | `cmd_git` | `git status --short -b` + `git log --oneline -3` |
| `/tastatus` | `cmd_status` | List active AI requests with elapsed time |
| `/taclear` | `cmd_clear` | Clear SQLite history + backend in-memory history |
| `/tainfo` | `cmd_info` | Repo, branch, AI backend, uptime, active tasks |
| `/tahelp` | `cmd_help` | Full command reference |
| _any other text_ | `forward_to_ai` | Sent to AI backend; history injected if `!is_stateful` |

---

## 3. CI/CD Pipeline

### Workflows

| File | Trigger | Jobs |
|---|---|---|
| `.github/workflows/ci.yml` | push/PR to any branch | lint (ruff) + test (pytest) + docker build |
| `.github/workflows/main-gate.yml` | push to `main` | version-check + tests + docker-build (3 independent jobs) |
| `.github/workflows/docker-publish.yml` | `main-gate` succeeds OR tag `v*.*.*` | build & push to `ghcr.io` |

### Version gate logic (`main-gate.yml` — `version-check` job)

```bash
VERSION=$(cat VERSION | tr -d '[:space:]')
LATEST_TAG=$(git tag --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
# Fails if VERSION matches LATEST_TAG (i.e. version was not bumped)
# Passes silently if no tags exist yet (first release)
```

**Release flow:** bump `VERSION` → merge to `main` → gate passes → image published → tag `vX.Y.Z` manually to create a release tag.

---

## 4. Test Coverage

**Overall: 46% (98 tests passing)**

| File | Coverage | Test type | Notes |
|---|---|---|---|
| `src/runtime.py` | 100% | unit | fully mocked subprocess |
| `src/ai/adapter.py` | 100% | contract | ABC interface |
| `src/ai/factory.py` | 100% | integration | checks backend type instantiation |
| `src/config.py` | 97% | unit | pydantic validation; 1 line missed in `Settings.load()` |
| `src/ai/copilot.py` | 95% | contract | 1 line missed (model override branch) |
| `src/executor.py` | 84% | unit | `run_shell()` subprocess not mocked |
| `src/history.py` | 84% | unit + integration | error-handling paths (new try/except) not exercised |
| `src/repo.py` | 66% | unit | `pull()` and `status()` not covered |
| `src/ai/codex.py` | 38% | contract | subprocess execution paths not mocked |
| `src/ai/direct.py` | 35% | contract | OpenAI/Anthropic client calls not mocked |
| `src/bot.py` | 28% | unit | only `_prefix` / `_is_allowed` tested; all handlers untested |
| `src/ai/session.py` | 25% | contract | PTY/pexpect untestable without live Copilot process |
| `src/main.py` | 0% | — | startup entrypoint, never exercised |

---

## 5. Known Gaps & To-Do (Technical Backlog)

---

### 5.1 Test Coverage — High Priority

**Goal: reach ~80% coverage**

#### 5.1.1 `bot.py` handler tests (currently 28%)

All Telegram handlers live in `_BotHandlers`. They require mocked `Update`, `ContextTypes`, and backend.

**Approach:**
```python
# conftest.py additions
from unittest.mock import AsyncMock, MagicMock, patch
from src.bot import build_app, _BotHandlers
from telegram import Update

def make_update(text="hello", chat_id="99999", user_id=42):
    update = MagicMock(spec=Update)
    update.effective_chat.id = int(chat_id)
    update.effective_user.id = user_id
    update.effective_message.text = text
    update.effective_message.reply_text = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    return update
```

**Tests needed:**
- `cmd_run`: safe cmd → `executor.run_shell` called; destructive cmd → inline keyboard shown; empty args → usage message
- `cmd_sync`: calls `repo.pull()`, sends result
- `cmd_git`: calls `repo.status()`, wraps in triple-backtick
- `cmd_status`: idle response; active AI entry shown with elapsed time
- `cmd_clear`: calls `history.clear_history` + `backend.clear_history`
- `forward_to_ai`: stateful backend → raw prompt; stateless → `history.build_context`; streaming path; error path → `⚠️ Error:`
- `_requires_auth` decorator: wrong chat_id → handler not called; wrong user → handler not called
- `callback_handler`: confirm → `executor.run_shell`; cancel → "Cancelled"

**File:** `tests/unit/test_bot_handlers.py`

---

#### 5.1.2 `executor.py` — `run_shell` (currently 84%)

```python
async def test_run_shell_success(monkeypatch):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"output\n", b""))
    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        result = await executor.run_shell("ls", 3000)
    assert "output" in result
    assert "[exit 0]" in result

async def test_run_shell_truncates_long_output():
    ...  # generate output > max_chars, verify truncation header appears
```

**File:** `tests/unit/test_executor.py` (extend existing)

---

#### 5.1.3 `repo.py` — `pull()` and `status()` (currently 66%)

```python
async def test_pull_no_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
    result = await repo_module.pull()
    assert "No repository" in result

async def test_pull_calls_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_module, "REPO_DIR", tmp_path)
    (tmp_path / ".git").mkdir()
    mock_repo = MagicMock()
    mock_repo.remotes.origin.pull.return_value = ["fetch result"]
    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_repo)):
        ...  # complex because to_thread is called twice

async def test_status_returns_git_output(tmp_path, monkeypatch):
    ...  # mock asyncio.create_subprocess_exec for both git calls
```

**File:** `tests/unit/test_repo.py` (extend existing)

---

#### 5.1.4 `history.py` — error paths (currently 84%)

The three new `try/except` blocks in `add_exchange`, `get_history`, `clear_history` are not covered.

```python
async def test_add_exchange_db_failure_is_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(history_module, "DB_PATH", tmp_path / "bad" / "history.db")
    # Parent dir doesn't exist → aiosqlite will fail
    await history_module.add_exchange("chat1", "msg", "resp")  # must not raise
    assert "Failed to save history" in caplog.text

async def test_get_history_db_failure_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "DB_PATH", Path("/nonexistent/path/db"))
    result = await history_module.get_history("chat1")
    assert result == []
```

**File:** `tests/unit/test_history.py` (extend existing)

---

#### 5.1.5 `ai/direct.py` — mocked API calls (currently 35%)

```python
async def test_openai_send(monkeypatch):
    backend = DirectAPIBackend("openai", "sk-test", "gpt-4o")
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Hello!"
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    backend._openai_client = mock_client  # inject cached client
    result = await backend.send("Hi")
    assert result == "Hello!"
    assert backend._messages[-1] == {"role": "assistant", "content": "Hello!"}

async def test_clear_history_resets_messages():
    backend = DirectAPIBackend("openai", "sk-test", "gpt-4o")
    backend._messages = [{"role": "user", "content": "test"}]
    backend.clear_history()
    assert backend._messages == []

async def test_unknown_provider_raises():
    backend = DirectAPIBackend("unknown", "key", "model")
    backend._messages = []
    with pytest.raises(ValueError, match="Unknown AI_PROVIDER"):
        await backend.send("hi")
```

**File:** `tests/unit/test_direct_backend.py`

---

#### 5.1.6 `main.py` — startup (currently 0%)

Integration test that mocks all side effects:

```python
async def test_startup_calls_all_phases(monkeypatch):
    monkeypatch.setattr("src.repo.clone", AsyncMock())
    monkeypatch.setattr("src.runtime.install_deps", AsyncMock(return_value="OK"))
    monkeypatch.setattr("src.history.init_db", AsyncMock())
    monkeypatch.setattr("src.bot.build_app", MagicMock(return_value=mock_app))
    # verify each phase called in order
```

**File:** `tests/integration/test_startup.py`

---

### 5.2 SQL todos (from session tracking)

These were planned tasks whose tracking in the session database was not fully completed:

| Task | Status | Notes |
|---|---|---|
| `pty-session` (ai/session.py) | `in_progress` | Implemented and working; session DB not updated to `done` |
| `bot-phase2` | `pending` | Implemented in bot.py (history pass-through, `/taclear`); session DB not updated |
| `history-inject` | `pending` | Implemented in `forward_to_ai` — stateless backends get `build_context()`; implemented |
| `infra-phase2` | `pending` | `/data` volume in Dockerfile + docker-compose + `init_db()` in main.py — all done |

All four "pending/in_progress" items are **actually implemented**. The session SQL was not updated as work was completed.

---

### 5.3 Coverage target: add `pytest-cov` to CI

Currently `pytest-cov` is installed locally but not in `requirements-dev.txt` and not reported in CI.

**Change needed in `requirements-dev.txt`:**
```
pytest-cov>=5.0
```

**Change needed in `.github/workflows/ci.yml` (test job):**
```yaml
- name: Run tests
  run: pytest tests/ -v --tb=short --cov=src --cov-fail-under=60
```

Start with `--cov-fail-under=60` and raise the threshold as coverage improves.

---

### 5.4 Copilot auth in Docker (known limitation)

The Copilot CLI requires interactive OAuth login (`gh auth login`) which cannot run headlessly in Docker. Current workaround: the `COPILOT_GITHUB_TOKEN` fine-grained PAT is passed via env var and Copilot CLI picks it up via `GH_TOKEN`.

**Issue:** if the PAT expires or has wrong scopes, the PTY session will hang at the auth prompt instead of returning an error. The `CopilotSession._spawn()` has a 30-second timeout on the initial prompt wait, but the failure message from Copilot is not surfaced clearly.

**Improvement needed:**
- Detect auth failure in `_spawn()` by looking for auth-related output before the `> ` prompt
- Surface a clear error to the Telegram user rather than a generic timeout

```python
# In CopilotSession._spawn():
child.expect([PROMPT_RE, "authenticate", "login", pexpect.TIMEOUT], timeout=30)
if child.match_index != 0:
    raise RuntimeError("Copilot auth failed — check COPILOT_GITHUB_TOKEN scope")
```

---

### 5.5 `/repo` path hardcoded in multiple files

`REPO_DIR = Path("/repo")` is defined independently in `session.py`, `codex.py`, `repo.py`, and `executor.py` (`cwd="/repo"`).

**Problem:** changing the repo mount point requires edits in 4 files.

**Proposed fix:** add `REPO_DIR` and `DB_PATH` to `config.py` as module-level constants (not pydantic fields, to avoid breaking test monkeypatching):

```python
# config.py bottom
from pathlib import Path
REPO_DIR = Path("/repo")
DB_PATH = Path("/data/history.db")
```

Then import from `src.config` in each file. Monkeypatching in tests would target `src.config.REPO_DIR` — needs test updates.

---

### 5.6 Streaming throttle is fixed at 1 second

`_THROTTLE = 1.0` in `bot.py` is hardcoded. Heavy users may want faster updates; rate-limited chats may need slower.

**Proposed:** add `STREAM_THROTTLE_SECS` env var to `BotConfig`:
```python
stream_throttle_secs: float = 1.0
```

---

### 5.7 No graceful shutdown

`asyncio.Event().wait()` in `main.py` blocks forever with no signal handling. On `docker stop`, the container gets `SIGTERM` → Python raises `KeyboardInterrupt` → `main()` catches it with a log. But the Copilot PTY session is not explicitly closed.

**Fix:** handle `SIGTERM` explicitly and call `session.close()` before exit.

```python
import signal

def _shutdown(sig, frame):
    logger.info("Received %s, shutting down…", signal.Signals(sig).name)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _shutdown)
```

And in the AI backend, expose a `close()` method through the `AICLIBackend` ABC.

---

## 6. Deployment Notes

### Running locally

```bash
cd /home/alien/docker/taVPNSentinel
docker compose up -d
docker compose logs -f
```

### Persistent repo (avoid re-cloning)

Set in `.env`:
```env
REPO_HOST_PATH=/home/alien/repos/VPNSentinel
```

The Docker volume mount becomes a bind mount to that host path.

### Adding a second project

```bash
mkdir /home/alien/docker/taMyAPI
cp /home/alien/docker/taVPNSentinel/.env /home/alien/docker/taMyAPI/.env
cp /home/alien/docker/taVPNSentinel/docker-compose.yml /home/alien/docker/taMyAPI/docker-compose.yml
# Edit .env: new TG_BOT_TOKEN, new GITHUB_REPO
cd /home/alien/docker/taMyAPI && docker compose up -d
```

Each stack is fully independent. Use separate Telegram bots (one per project via BotFather).

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
| `anthropic` | `>=0.25` | Anthropic direct API |
| Node.js | LTS (NodeSource) | Required by Copilot CLI (`@github/copilot`) |
| `@github/copilot` (npm) | latest | Copilot CLI — **not** `@githubnext/github-copilot-cli` (deprecated) |
