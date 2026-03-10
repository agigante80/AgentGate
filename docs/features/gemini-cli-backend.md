# Gemini CLI Backend

> Status: **Planned** | Priority: Medium

Add `AI_CLI=gemini` as a first-class backend, backed by Google's official
[Gemini CLI](https://github.com/google-gemini/gemini-cli) (`@google/gemini-cli`).
This enables AgentGate to use Gemini 2.5 Pro (and future Gemini models) for free
via a personal Google Account, with no OpenAI/Anthropic dependency.

---

## Background

Google released the **Gemini CLI** in June 2025 (Apache 2.0, open source).

Key facts relevant to AgentGate:

| Property | Value |
|----------|-------|
| Install | `npm install -g @google/gemini-cli` |
| Binary | `gemini` |
| Non-interactive invocation | `gemini "your prompt"` |
| Streaming | Yes — line-buffered stdout |
| Auth (API key) | `GEMINI_API_KEY` env var |
| Auth (OAuth, free tier) | Interactive Google Account login (not suitable for Docker/headless) |
| Free-tier quota | Gemini 2.5 Pro · 60 req/min · 1 000 req/day |
| Context window | 1 million tokens |
| License | Apache 2.0 |
| GitHub | https://github.com/google-gemini/gemini-cli |

The CLI supports both interactive REPL mode and a non-interactive single-prompt
mode (e.g. `gemini -p "explain this"`). AgentGate will use the non-interactive mode,
mirroring how the `copilot` backend works today.

---

## Usage (env vars)

```env
AI_CLI=gemini
GEMINI_API_KEY=AIza...          # from https://aistudio.google.com/app/apikey
AI_MODEL=gemini-2.5-pro         # optional — omit to use CLI default
AI_CLI_OPTS=                    # optional verbatim extra flags passed to gemini
```

No other config changes are needed. All existing `BotConfig`, `VoiceConfig`, and
platform settings remain unchanged.

---

## Behaviour

- **Stateless** (`is_stateful = False`) — same pattern as `CopilotBackend`.
  AgentGate injects the last 10 history exchanges via `build_prompt()` before
  each call.
- **Streaming** — stdout is read line-by-line and yielded to the Telegram/Slack
  streaming handler. Throttled by `STREAM_THROTTLE_SECS` as usual.
- **Model selection** — if `AI_MODEL` is set, pass it via `--model <value>`.
  If unset, the CLI uses its own default (currently `gemini-2.5-pro`).
- **Extra opts** — `AI_CLI_OPTS` is split with `shlex` and appended verbatim,
  exactly as `CodexBackend` does.

---

## Architecture

### New file: `src/ai/gemini.py`

```python
import asyncio
import logging
import os
import shlex
from collections.abc import AsyncGenerator

from src.ai.adapter import AICLIBackend, SubprocessMixin

logger = logging.getLogger(__name__)


class GeminiBackend(SubprocessMixin, AICLIBackend):
    """Stateless backend using Google's official Gemini CLI."""

    is_stateful = False

    def __init__(self, api_key: str, model: str = "", opts: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._opts = opts

    def _make_cmd(self, prompt: str) -> tuple[list[str], dict]:
        env = {**os.environ, "GEMINI_API_KEY": self._api_key}
        cmd = ["gemini", "-p", prompt, "--yolo"]   # --yolo = non-interactive/no-confirm
        if self._model:
            cmd += ["--model", self._model]
        if self._opts:
            cmd += shlex.split(self._opts)
        return cmd, env

    async def send(self, prompt: str) -> str:
        cmd, env = self._make_cmd(prompt)
        proc = await self._spawn(cmd, env)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode().strip() or stdout.decode().strip()
            logger.error("gemini CLI error: %s", err)
            return f"⚠️ Gemini error:\n{err}"
        return stdout.decode().strip()

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        cmd, env = self._make_cmd(prompt)
        proc = await self._spawn(cmd, env)
        assert proc.stdout
        async for line in proc.stdout:
            yield line.decode()
        await proc.wait()
        if proc.returncode != 0:
            assert proc.stderr
            err = (await proc.stderr.read()).decode().strip()
            if err:
                logger.error("gemini CLI stream error: %s", err)
                yield f"\n⚠️ Gemini error:\n{err}"
```

> **Note on `--yolo` flag**: Gemini CLI's non-interactive flag may differ across
> versions. Verify the correct flag at implementation time — candidates are
> `--yolo`, `--no-interactive`, or `-p` alone. Pin a minimum version in
> `requirements.txt` / Dockerfile once confirmed.

---

## Files to Create / Change

| File | Change |
|------|--------|
| `src/ai/gemini.py` | **New** — `GeminiBackend` class (see above) |
| `src/ai/factory.py` | Add `if ai.ai_cli == "gemini":` branch |
| `src/config.py` | Extend `ai_cli` Literal to include `"gemini"`; add `gemini_api_key` field |
| `Dockerfile` | Install Node.js + `npm install -g @google/gemini-cli` |
| `requirements.txt` | No Python deps needed |
| `README.md` | Document `AI_CLI=gemini` option in the configuration table |
| `tests/unit/test_gemini_backend.py` | **New** — unit tests (see below) |
| `tests/contract/test_backends.py` | Ensure `GeminiBackend` satisfies `AICLIBackend` contract |

### `src/ai/factory.py` delta

```python
    if ai.ai_cli == "gemini":
        from src.ai.gemini import GeminiBackend
        return GeminiBackend(
            api_key=ai.gemini_api_key or ai.ai_api_key,
            model=ai.ai_model,
            opts=ai.ai_cli_opts,
        )
```

### `src/config.py` delta

```python
    ai_cli: Literal["copilot", "codex", "api", "gemini"] = "copilot"
    # ...existing fields...
    gemini_api_key: str = ""   # GEMINI_API_KEY — falls back to AI_API_KEY if empty
```

The `gemini_api_key` field allows users to keep a dedicated `GEMINI_API_KEY` without
conflicting with an existing `AI_API_KEY` used for another provider.

### `Dockerfile` delta

```dockerfile
# Install Node.js (for Gemini CLI) — only when AI_CLI=gemini
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @google/gemini-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

**Alternative (multi-stage / conditional):** To avoid bloating the default image
(~400 MB for Node), consider making this an optional build arg:

```dockerfile
ARG INSTALL_GEMINI=false
RUN if [ "$INSTALL_GEMINI" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs npm \
        && npm install -g @google/gemini-cli; \
    fi
```

Users building with Gemini CLI: `docker build --build-arg INSTALL_GEMINI=true .`

---

## Tests to Write

### `tests/unit/test_gemini_backend.py`

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.ai.gemini import GeminiBackend


@pytest.fixture
def backend():
    return GeminiBackend(api_key="test-key", model="gemini-2.5-pro")


def test_make_cmd_basic(backend):
    cmd, env = backend._make_cmd("hello")
    assert "gemini" in cmd
    assert "-p" in cmd
    assert "hello" in cmd
    assert env["GEMINI_API_KEY"] == "test-key"


def test_make_cmd_model(backend):
    cmd, _ = backend._make_cmd("hello")
    assert "--model" in cmd
    assert "gemini-2.5-pro" in cmd


def test_make_cmd_no_model():
    b = GeminiBackend(api_key="k")
    cmd, _ = b._make_cmd("hello")
    assert "--model" not in cmd


def test_make_cmd_opts():
    b = GeminiBackend(api_key="k", opts="--debug --verbose")
    cmd, _ = b._make_cmd("hello")
    assert "--debug" in cmd
    assert "--verbose" in cmd


@pytest.mark.asyncio
async def test_send_success(backend):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"Hello from Gemini", b"")
    with patch.object(backend, "_spawn", return_value=mock_proc):
        result = await backend.send("hello")
    assert result == "Hello from Gemini"


@pytest.mark.asyncio
async def test_send_error(backend):
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"auth error")
    with patch.object(backend, "_spawn", return_value=mock_proc):
        result = await backend.send("hello")
    assert "⚠️" in result
    assert "auth error" in result


def test_is_stateless(backend):
    assert backend.is_stateful is False
```

---

## Open Questions / Risks

| # | Question | Notes |
|---|----------|-------|
| 1 | **Non-interactive flag** | Gemini CLI flag for headless mode may change across versions. Verify `--yolo` vs. `-p` alone. |
| 2 | **Output format** | Gemini CLI may emit ANSI colour codes or markdown decorators in stdout. May need to strip them before forwarding. |
| 3 | **Free tier suitable for bots?** | 1 000 req/day ÷ 60 req/min is fine for personal use. Multi-user deployments need an API key. |
| 4 | **Dockerfile size** | Node.js + npm adds ~200 MB. Consider optional `INSTALL_GEMINI` build arg to keep default image lean. |
| 5 | **Auth flow (OAuth)** | The free personal-account flow requires a browser for first-time auth. Not usable in Docker headless. API key (`GEMINI_API_KEY`) required for container deployments. |
| 6 | **Streaming protocol** | Verify that `gemini -p "…" --yolo` actually streams stdout progressively vs. buffering until done. |
| 7 | **Tool use / function calling** | Gemini CLI supports MCP servers and built-in tools (web search, shell). These may interfere with AgentGate's executor. Recommend disabling with a flag if possible. |

---

## Pros and Cons vs. Existing Backends

| | `AI_CLI=gemini` | `AI_CLI=copilot` | `AI_CLI=api` (OpenAI) |
|-|-----------------|-------------------|----------------------|
| **Free tier** | ✅ Generous (1000 req/day) | ✅ GitHub Copilot subscription | ❌ Pay-per-token |
| **Model** | Gemini 2.5 Pro (1M ctx) | GPT-4o / Claude (varies) | Any OpenAI/Anthropic |
| **Context window** | 1M tokens | ~128K tokens | Up to 200K (o3) |
| **Stateful/Stateless** | Stateless (history injected) | Stateless | Stateless |
| **Docker complexity** | ⚠️ Needs Node.js | ⚠️ Needs `gh` CLI + auth | ✅ Pure Python |
| **Streaming** | ✅ | ✅ | ✅ |
| **Privacy** | Data sent to Google | Data sent to GitHub/OpenAI | Data sent to provider |
| **Offline** | ❌ | ❌ | ❌ (unless Ollama) |
