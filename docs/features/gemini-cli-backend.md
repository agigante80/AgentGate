# Gemini CLI Backend

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-11

Add `AI_CLI=gemini` as a first-class backend, backed by Google's official
[Gemini CLI](https://github.com/google-gemini/gemini-cli) (`@google/gemini-cli`).
This enables AgentGate to use Gemini 2.5 Pro (and future Gemini models) via a
dedicated Google AI Studio API key, with no OpenAI/Anthropic dependency.

---

## Background

Google released the **Gemini CLI** in June 2025 (Apache 2.0, open source).

Key facts relevant to AgentGate:

| Property | Value |
|----------|-------|
| Install | `npm install -g @google/gemini-cli` |
| Binary | `gemini` |
| Non-interactive invocation | `gemini --non-interactive -p "prompt"` |
| Auth (API key) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` env var |
| Auth (OAuth, free tier) | Interactive browser login — **not suitable for Docker/headless** |
| Free-tier quota | Gemini 2.5 Pro · 60 req/min · 1 000 req/day (personal Google account) |
| Paid quota | Higher limits via API key from [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| Context window | 1 million tokens |
| Exit codes | 0 = success · 1 = general error · 42 = invalid input · 53 = turn limit exceeded |
| ANSI stripping | Automatic when stdout is not a TTY (i.e. piped — always the case in subprocess mode) |
| License | Apache 2.0 |
| GitHub | https://github.com/google-gemini/gemini-cli |
| Docs | https://google-gemini.github.io/gemini-cli/ |

The CLI supports both interactive REPL mode and a non-interactive single-prompt
mode. AgentGate uses the non-interactive mode, mirroring how `CopilotBackend`
and `CodexBackend` work today.

### Critical flag clarification

The Gemini CLI has **two distinct flags** that are often confused:

| Flag | Purpose | Required for AgentGate? |
|------|---------|------------------------|
| `--non-interactive` | Disables interactive prompts (auth dialogs, confirmations). Enables headless/scripted use. | ✅ **Yes — always** |
| `--yolo` | Auto-approves Gemini's **built-in tool calls** (web search, shell exec, file writes). Separate from interactive mode. | ⚠️ Optional — only if tool use is enabled |

**Do not conflate them.** A subprocess run with only `--yolo` will still hang waiting for auth input if no API key is set. Always use `--non-interactive` for headless execution.

---

## Usage (env vars)

```env
AI_CLI=gemini
GEMINI_API_KEY=AIza...          # from https://aistudio.google.com/app/apikey
AI_MODEL=gemini-2.5-pro         # optional — omit to use CLI default
AI_CLI_OPTS=                    # optional verbatim extra flags passed to gemini
```

`GOOGLE_API_KEY` is accepted as an alternative to `GEMINI_API_KEY` by the CLI
itself, but `GEMINI_API_KEY` is preferred for clarity in AgentGate `.env` files.

> ⚠️ **API key required for Docker.** The free personal-account flow requires a
> browser for first-time OAuth. Use an API key from Google AI Studio for all
> container deployments.

No other config changes are needed. All existing `BotConfig`, `VoiceConfig`, and
platform settings remain unchanged.

---

## Behaviour

- **Stateless** (`is_stateful = False`) — same pattern as `CopilotBackend`.
  AgentGate injects the last 10 history exchanges via `build_prompt()` (called
  by `forward_to_ai` in `bot.py` / `slack.py`) before each call.
- **Streaming** — stdout is read line-by-line and yielded to the Telegram/Slack
  streaming handler. Throttled by `STREAM_THROTTLE_SECS` as usual.
- **ANSI codes** — automatically stripped by the Gemini CLI when stdout is a pipe
  (which is always the case in `asyncio.create_subprocess_exec`). No manual
  stripping needed in AgentGate code.
- **Model selection** — if `AI_MODEL` is set, pass it via `--model <value>`.
  The shorthand is `-m`. If unset, the CLI uses its own default.
- **Extra opts** — `AI_CLI_OPTS` is split with `shlex` and appended verbatim,
  exactly as `CodexBackend` does. When set, it **replaces** the default
  `--non-interactive` flag, so users must include it explicitly.
- **Timeout** — `send()` applies a 180s hard timeout (same as `CopilotSession`)
  to prevent the process hanging if the API is unavailable.
- **Tool use / MCP** — Gemini CLI supports web search, shell execution, and MCP
  servers by default. These can conflict with AgentGate's own `executor.py`.
  Disable with `AI_CLI_OPTS=--non-interactive --no-tools` (verify flag name at
  implementation time; alternatively `--tool-discovery-enabled=false`).
- **Working directory** — `SubprocessMixin._spawn()` runs in `REPO_DIR` (`/repo`),
  so Gemini can access project files via the `@filename` syntax.
- **`clear_history()`** — no-op (inherited from `AICLIBackend` base class).
  The backend is stateless; history is injected into each prompt by the bot layer.

---

## Architecture

### New file: `src/ai/gemini.py`

```python
"""
Gemini CLI backend — non-interactive subprocess mode.
Each query spawns `gemini --non-interactive -p <prompt>` as a subprocess.
History is injected by the bot layer via build_prompt() (stateless pattern).
"""
import asyncio
import logging
import os
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin

logger = logging.getLogger(__name__)

TIMEOUT = 180  # seconds — same as CopilotSession


class GeminiBackend(SubprocessMixin, AICLIBackend):
    """Stateless backend using Google's official Gemini CLI."""

    is_stateful = False

    def __init__(self, api_key: str, model: str = "", opts: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._opts = opts

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        env = {**os.environ, "GEMINI_API_KEY": self._api_key}
        # --non-interactive: prevents auth dialogs and interactive prompts in headless mode.
        # This is distinct from --yolo (which auto-approves built-in tool calls).
        extra = shlex.split(self._opts) if self._opts else ["--non-interactive"]
        cmd = ["gemini", "-p", prompt] + extra
        if self._model:
            cmd += ["--model", self._model]
        return cmd, env

    async def send(self, prompt: str) -> str:
        cmd, env = self._make_cmd(prompt)
        try:
            proc = await self._spawn(cmd, env)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return f"⚠️ Gemini timed out after {TIMEOUT}s."
        except Exception as exc:
            logger.exception("Gemini subprocess error")
            return f"⚠️ Gemini error: {exc}"
        if proc.returncode not in (0, None):
            err = stderr.decode().strip() or stdout.decode().strip()
            rc = proc.returncode
            suffix = {42: " (invalid input)", 53: " (turn limit exceeded)"}.get(rc, "")
            logger.error("gemini CLI error (rc=%d%s): %s", rc, suffix, err)
            return f"⚠️ Gemini error (rc={rc}{suffix}):\n{err}"
        return stdout.decode().strip()

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        cmd, env = self._make_cmd(prompt)
        try:
            proc = await self._spawn(cmd, env)
        except Exception as exc:
            logger.exception("Gemini stream error")
            yield f"⚠️ Gemini error: {exc}"
            return
        assert proc.stdout
        try:
            async for line in proc.stdout:
                yield line.decode()
        except Exception as exc:
            logger.exception("Gemini stream read error")
            yield f"\n⚠️ Gemini stream error: {exc}"
            return
        finally:
            await proc.wait()
        if proc.returncode not in (0, None):
            assert proc.stderr
            err = (await proc.stderr.read()).decode().strip()
            rc = proc.returncode
            suffix = {42: " (invalid input)", 53: " (turn limit exceeded)"}.get(rc, "")
            if err:
                logger.error("gemini CLI stream error (rc=%d%s): %s", rc, suffix, err)
                yield f"\n⚠️ Gemini error (rc={rc}{suffix}):\n{err}"
```

---

## Files to Create / Change

| File | Change | Notes |
|------|--------|-------|
| `src/ai/gemini.py` | **New** — `GeminiBackend` class (see above) | ~70 lines |
| `src/ai/factory.py` | Add `if ai.ai_cli == "gemini":` branch | 5 lines |
| `src/config.py` | Extend `AIConfig`: `ai_cli` Literal + `gemini_api_key` field | 2 lines |
| `Dockerfile` | Add `npm install -g @google/gemini-cli` (Node.js **already present**) | 1 line |
| `README.md` | Add `gemini` to `AI_CLI` row; add `GEMINI_API_KEY` row (×2 — Telegram + Slack sections) | ~4 lines |
| `tests/unit/test_gemini_backend.py` | **New** — unit tests (see below) | ~80 lines |
| `tests/contract/test_backends_contract.py` | Add `GeminiBackend` to `ALL_BACKENDS` | ~5 lines |
| `tests/integration/test_factory.py` | Add factory test for `AI_CLI=gemini` | ~10 lines |

---

## Step-by-Step Implementation

### Step 1 — `src/config.py`

In `AIConfig`, make two changes:

```python
# Before:
ai_cli: Literal["copilot", "codex", "api"] = "copilot"

# After:
ai_cli: Literal["copilot", "codex", "api", "gemini"] = "copilot"
```

Add after the existing `ai_cli_opts` field:

```python
gemini_api_key: str = ""   # GEMINI_API_KEY — falls back to AI_API_KEY if empty
```

The `gemini_api_key` field reads from `GEMINI_API_KEY` (Pydantic auto-maps field
name to env var in uppercase). The factory falls back to `ai_api_key` (`AI_API_KEY`)
so users who already have a generic key set don't need a duplicate.

### Step 2 — `src/ai/gemini.py`

Create the file with the implementation shown in the Architecture section above.

### Step 3 — `src/ai/factory.py`

Add the `gemini` branch before the final `raise ValueError`:

```python
    if ai.ai_cli == "gemini":
        from src.ai.gemini import GeminiBackend
        return GeminiBackend(
            api_key=ai.gemini_api_key or ai.ai_api_key,
            model=ai.ai_model,
            opts=ai.ai_cli_opts,
        )
```

### Step 4 — `Dockerfile`

Node.js is **already installed** in the base image via the NodeSource block. Only
add the Gemini CLI global install, alongside the existing Copilot and Codex lines:

```dockerfile
# Before (existing lines):
# GitHub Copilot CLI — pinned version (update via Dependabot)
RUN npm install -g @github/copilot@0.0.421

# OpenAI Codex CLI — pinned version (update via Dependabot)
RUN npm install -g @openai/codex@0.111.0

# After — add:
# Google Gemini CLI — pinned version (update via Dependabot)
RUN npm install -g @google/gemini-cli@<latest-version>
```

> ⚠️ **Pin the version.** Find the latest version with `npm show @google/gemini-cli
> version` and hardcode it. Dependabot will keep it updated (it already tracks npm
> packages for this project via `docs/features/npm-dependabot.md`).

> ℹ️ **No Docker size impact.** Node.js is already ~200 MB in the image for Copilot
> and Codex CLIs. Adding `@google/gemini-cli` adds only ~50–100 MB (the npm
> package itself). The optional build-arg approach is unnecessary here.

### Step 5 — `README.md`

Two tables must be updated (Telegram section ≈ line 158, Slack section ≈ line 447):

**`AI_CLI` row** — extend the allowed values:
```markdown
# Before:
| `AI_CLI` | `copilot` | `copilot` \| `codex` \| `api` |

# After:
| `AI_CLI` | `copilot` | `copilot` \| `codex` \| `api` \| `gemini` |
```

**Add `GEMINI_API_KEY` row** — insert after the `COPILOT_GITHUB_TOKEN` row:
```markdown
| `GEMINI_API_KEY` | — | API key for the `gemini` backend (from [AI Studio](https://aistudio.google.com/app/apikey)). Falls back to `AI_API_KEY` if unset. |
```

**Update `AI_CLI_OPTS` description** — add the Gemini default:
```markdown
# Before:
... (Copilot: `--allow-all`; Codex: `--approval-mode full-auto`) ...

# After:
... (Copilot: `--allow-all`; Codex: `--approval-mode full-auto`; Gemini: `--non-interactive`) ...
```

### Step 6 — Tests

#### `tests/unit/test_gemini_backend.py` (new file)

```python
"""
Tests for GeminiBackend (src/ai/gemini.py).
All subprocess I/O is fully mocked — no real gemini process is spawned.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.gemini import GeminiBackend, TIMEOUT


# ── Helpers ────────────────────────────────────────────────────────────────────

class _AsyncIter:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _make_proc(stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.wait = AsyncMock()
    lines = stdout.splitlines(keepends=True)
    proc.stdout.__aiter__ = MagicMock(return_value=_AsyncIter(lines))
    return proc


# ── Construction ───────────────────────────────────────────────────────────────

class TestConstruction:
    def test_stores_fields(self):
        b = GeminiBackend(api_key="k", model="gemini-2.5-pro", opts="--debug")
        assert b._api_key == "k"
        assert b._model == "gemini-2.5-pro"
        assert b._opts == "--debug"

    def test_not_stateful(self):
        assert GeminiBackend(api_key="k").is_stateful is False


# ── _make_cmd ─────────────────────────────────────────────────────────────────

class TestMakeCmd:
    def test_default_cmd_has_non_interactive(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("hello")
        assert "--non-interactive" in cmd

    def test_prompt_in_cmd(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("my prompt")
        assert "-p" in cmd
        assert "my prompt" in cmd

    def test_env_contains_api_key(self):
        b = GeminiBackend(api_key="AIzaXYZ")
        _, env = b._make_cmd("hello")
        assert env["GEMINI_API_KEY"] == "AIzaXYZ"

    def test_model_flag_added_when_set(self):
        b = GeminiBackend(api_key="k", model="gemini-2.5-pro")
        cmd, _ = b._make_cmd("hi")
        assert "--model" in cmd
        assert "gemini-2.5-pro" in cmd

    def test_model_flag_absent_when_empty(self):
        b = GeminiBackend(api_key="k")
        cmd, _ = b._make_cmd("hi")
        assert "--model" not in cmd

    def test_opts_replaces_non_interactive(self):
        b = GeminiBackend(api_key="k", opts="--non-interactive --yolo")
        cmd, _ = b._make_cmd("hi")
        assert "--yolo" in cmd
        # opts replaces defaults, so --non-interactive comes from opts
        assert cmd.count("--non-interactive") == 1

    def test_custom_opts_parsed_with_shlex(self):
        b = GeminiBackend(api_key="k", opts="--debug --sandbox")
        cmd, _ = b._make_cmd("hi")
        assert "--debug" in cmd
        assert "--sandbox" in cmd
        assert "--non-interactive" not in cmd  # custom opts replaces defaults


# ── send() ─────────────────────────────────────────────────────────────────────

class TestSend:
    async def test_send_success(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"Hello from Gemini")
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert result == "Hello from Gemini"

    async def test_send_error_rc1(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"auth error", returncode=1)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "⚠️" in result
        assert "auth error" in result

    async def test_send_error_rc42_invalid_input(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"bad prompt", returncode=42)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "invalid input" in result

    async def test_send_error_rc53_turn_limit(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"", stderr=b"rate limit", returncode=53)
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert "turn limit" in result

    async def test_send_timeout(self):
        b = GeminiBackend(api_key="k")
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = AsyncMock()
        with patch.object(b, "_spawn", return_value=proc):
            result = await b.send("hello")
        assert f"{TIMEOUT}s" in result
        assert "⚠️" in result


# ── stream() ───────────────────────────────────────────────────────────────────

class TestStream:
    async def test_stream_yields_lines(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"line1\nline2\n")
        with patch.object(b, "_spawn", return_value=proc):
            chunks = [c async for c in b.stream("hello")]
        assert "".join(chunks).strip() == "line1\nline2"

    async def test_stream_error_appended(self):
        b = GeminiBackend(api_key="k")
        proc = _make_proc(stdout=b"partial", stderr=b"stream error", returncode=1)
        with patch.object(b, "_spawn", return_value=proc):
            chunks = [c async for c in b.stream("hello")]
        full = "".join(chunks)
        assert "⚠️" in full
        assert "stream error" in full


# ── clear_history ──────────────────────────────────────────────────────────────

class TestClearHistory:
    def test_clear_history_does_not_raise(self):
        b = GeminiBackend(api_key="k")
        b.clear_history()  # no-op inherited from AICLIBackend — must not raise
```

#### `tests/contract/test_backends_contract.py` — additions

Add to the imports and `ALL_BACKENDS` list:

```python
# Add to imports:
from src.ai.gemini import GeminiBackend

# Add make_ helper:
def make_gemini():
    return GeminiBackend(api_key="test-key", model="gemini-2.5-pro")

# Add to ALL_BACKENDS:
ALL_BACKENDS = [
    pytest.param(make_copilot, id="copilot"),
    pytest.param(make_codex, id="codex"),
    pytest.param(make_direct, id="direct"),
    pytest.param(make_gemini, id="gemini"),  # ← ADD THIS
]

# Add to TestAdapterContract:
def test_gemini_is_not_stateful(self):
    assert make_gemini().is_stateful is False
```

#### `tests/integration/test_factory.py` — addition

```python
def test_creates_gemini_backend(self, monkeypatch):
    monkeypatch.setenv("AI_CLI", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTest")
    cfg = AIConfig()
    backend = create_backend(cfg)
    assert isinstance(backend, GeminiBackend)
    assert backend._api_key == "AIzaTest"

def test_gemini_falls_back_to_ai_api_key(self, monkeypatch):
    monkeypatch.setenv("AI_CLI", "gemini")
    monkeypatch.setenv("AI_API_KEY", "fallback-key")
    # GEMINI_API_KEY not set
    cfg = AIConfig()
    backend = create_backend(cfg)
    assert backend._api_key == "fallback-key"

def test_gemini_model_passed_through(self, monkeypatch):
    monkeypatch.setenv("AI_CLI", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("AI_MODEL", "gemini-2.0-flash")
    cfg = AIConfig()
    backend = create_backend(cfg)
    assert backend._model == "gemini-2.0-flash"
```

---

## Open Questions / Risks

| # | Question | Status | Notes |
|---|----------|--------|-------|
| 1 | **`--non-interactive` flag stability** | ✅ Confirmed | Documented in official headless.md. Stable across versions. Use alongside `-p`. |
| 2 | **`--yolo` flag** | ⚠️ Optional | Auto-approves built-in tool calls (web search, shell). Separate from non-interactive mode. Only needed if Gemini tool use is desired; keep disabled by default. |
| 3 | **ANSI codes in output** | ✅ Non-issue | CLI auto-strips ANSI when stdout is not a TTY. `asyncio.create_subprocess_exec` always pipes stdout. |
| 4 | **Streaming is buffered or progressive?** | 🔍 Verify at impl | Test whether `gemini -p "…" --non-interactive` streams progressively or buffers. If buffered, only `send()` is meaningful; `stream()` can delegate to `send()`. |
| 5 | **Built-in tool calls interfere with executor?** | 🔍 Verify at impl | Gemini's built-in tools (web search, shell exec) may attempt to modify files in `REPO_DIR`. Recommend `--no-tools` or equivalent flag to disable. Verify flag name from `gemini --help`. |
| 6 | **Trailing footer?** | 🔍 Verify at impl | Copilot CLI appends `Total usage est: …` which `CopilotSession` strips. Check whether Gemini CLI appends similar metadata and strip if needed. |
| 7 | **Turn limit (rc=53)** | ✅ Documented | Exit code 53 = turn limit exceeded. Handled in `send()` and `stream()` with labelled error messages. |
| 8 | **`GOOGLE_API_KEY` vs `GEMINI_API_KEY`** | ✅ Clarified | Both accepted by the CLI. AgentGate uses `GEMINI_API_KEY` field (reads `GEMINI_API_KEY` env var) for clarity; `GOOGLE_API_KEY` works as a silent fallback if the CLI prefers it. |

---

## Pros and Cons vs. Existing Backends

| | `AI_CLI=gemini` | `AI_CLI=copilot` | `AI_CLI=codex` | `AI_CLI=api` (OpenAI) |
|-|-----------------|-------------------|----------------|----------------------|
| **Free tier** | ✅ 1 000 req/day (personal account) | ✅ GitHub Copilot subscription | ❌ Pay-per-token | ❌ Pay-per-token |
| **Paid tier** | ✅ API key from AI Studio | — | OpenAI billing | OpenAI / Anthropic billing |
| **Model** | Gemini 2.5 Pro (1M ctx) | GPT-4o / Claude (varies) | o3/o4 | Any OpenAI/Anthropic |
| **Context window** | 1M tokens | ~128K tokens | ~200K (o3) | Up to 200K |
| **Stateful/Stateless** | Stateless (history injected) | Stateless | Stateless | Stateful (native) |
| **Docker image impact** | ✅ Node.js already installed | ⚠️ Needs `gh` CLI + auth | ✅ Node.js already installed | ✅ Pure Python |
| **Streaming** | ✅ (verify progressiveness) | ✅ | ✅ | ✅ |
| **Privacy** | Data sent to Google | Data sent to GitHub/OpenAI | Data sent to OpenAI | Data sent to provider |
| **Offline** | ❌ | ❌ | ❌ | ❌ (unless Ollama) |
| **Built-in tools** | ⚠️ Web search, shell (disable recommended) | ✅ Code-focused tools | ✅ Code-focused | ❌ (none via CLI) |
