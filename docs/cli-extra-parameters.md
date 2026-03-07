# CLI Extra Parameters — Design Document

> Status: **Planning**
> Branch: `develop`

This document analyses the options for exposing extra CLI flags to the AI backends (Copilot CLI, Codex CLI) via TeleAgent environment variables. It covers what is already implemented, a deep review of each backend's relevant options, and four design options with a recommendation.

---

## 1. Current State

### 1.1 Copilot CLI (`AI_CLI=copilot`)

Invocation in `src/ai/session.py`:

```python
args = ["copilot", "-p", prompt, "--allow-all"]
if self._model:
    args += ["--model", self._model]
```

**`--allow-all` is already hardcoded.** It is equivalent to:
- `--allow-all-tools` — all tools run automatically without confirmation
- `--allow-all-paths` — file path verification disabled, any path accessible
- `--allow-all-urls` — all URLs accessible without confirmation

This gives Copilot **full authority** — no interactive permission prompts. The model is optionally configurable via `COPILOT_MODEL`.

### 1.2 Codex CLI (`AI_CLI=codex`)

Invocation in `src/ai/codex.py`:

```python
cmd = ["codex", prompt, "--approval-mode", "auto", "--model", self._model]
```

`--approval-mode auto` is hardcoded. However, valid approval mode values per Codex CLI docs are `suggest`, `auto-edit`, and `full-auto` — **`auto` is not a documented value** and may silently fall back to the default (`suggest`). The model is configurable via `CODEX_MODEL` (default: `o3`).

### 1.3 Direct API (`AI_CLI=api`)

No subprocess CLI is involved — the Direct API backend calls OpenAI/Anthropic/Ollama APIs directly via Python SDK. CLI flag concepts do not apply.

---

## 2. Copilot CLI — Relevant Options Deep Review

> Source: `copilot --help` (installed version: 0.0.421)

### Permission / authority flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--allow-all` | Enable all permissions (tools + paths + URLs) | **Currently hardcoded** |
| `--allow-all-tools` | Auto-run all tools without confirmation | Env: `COPILOT_ALLOW_ALL` |
| `--allow-all-paths` | Disable file path verification | — |
| `--allow-all-urls` | Allow access to all URLs without confirmation | — |
| `--allow-tool <tool>` | Whitelist specific tools (repeatable) | Granular alternative |
| `--deny-tool <tool>` | Blacklist specific tools (repeatable) | Overrides allow-list |
| `--allow-url <url>` | Allow specific URLs/domains (repeatable) | Granular alternative |
| `--deny-url <url>` | Deny specific URLs/domains (repeatable) | Takes precedence |
| `--available-tools <tools>` | Limit the tool set available to the model | — |
| `--yolo` | Alias for `--allow-all` | — |

### Model and execution flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--model <model>` | AI model override | **Configurable via `COPILOT_MODEL`** |
| `--autopilot` | Enable autopilot continuation in prompt mode | Useful for multi-step tasks |
| `--max-autopilot-continues <n>` | Cap autopilot continuation steps | Default: unlimited |
| `--no-ask-user` | Agent works autonomously; disables ask_user tool | — |
| `-s, --silent` | Output only the agent response (no stats) | Useful for scripting |

### Directory and MCP flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--add-dir <directory>` | Add directory to allowed list (repeatable) | — |
| `--disallow-temp-dir` | Prevent auto access to system temp dir | — |
| `--additional-mcp-config <json>` | Extra MCP server config as JSON or file path | — |
| `--add-github-mcp-tool <tool>` | Enable specific GitHub MCP tools | `"*"` for all |
| `--enable-all-github-mcp-tools` | Enable all GitHub MCP server tools | — |
| `--disable-builtin-mcps` | Disable all built-in MCP servers | — |

### Session flags (prompt mode)

| Flag | Description | Notes |
|------|-------------|-------|
| `--continue` | Resume the most recent session | — |
| `--resume [sessionId]` | Resume a previous session | — |
| `--share [path]` | Share session to markdown after completion | — |
| `--share-gist` | Share session to a secret GitHub gist | — |
| `--output-format <format>` | `text` or `json` (JSONL) | — |
| `--stream <on|off>` | Enable/disable streaming mode | — |

### Notes on Copilot environment variables

| Env var | Equivalent flag |
|---------|----------------|
| `COPILOT_ALLOW_ALL` | `--allow-all-tools` (tools only, not full `--allow-all`) |
| `GH_TOKEN` / `COPILOT_GITHUB_TOKEN` | Authentication token |

---

## 3. Codex CLI — Relevant Options Deep Review

> Source: OpenAI Codex CLI documentation (v0.111.0 as installed in Docker image)

### Approval / authority flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--approval-mode suggest` | Every file change and command needs manual approval | Default / safest |
| `--approval-mode auto-edit` | File edits auto-applied; commands need approval | Current intent (`auto`) |
| `--approval-mode full-auto` | Files and commands fully automated | Max authority |
| `--full-auto` | Shortcut for `--approval-mode full-auto` | — |
| `--dangerously-bypass-approvals-and-sandbox` | No restrictions | ⚠️ Dangerous |
| `--yolo` | Alias for above | ⚠️ Dangerous |

> ⚠️ **Current bug**: the code uses `--approval-mode auto` which is **not a valid value**. The correct value for auto-applying file edits is `auto-edit`. This should be fixed to `full-auto` to match the intent of running headless in a container.

### Model and execution flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--model <model>` / `-m` | Model selection | **Configurable via `CODEX_MODEL`** |
| `--sandbox <mode>` | Sandboxing: `read-only`, `workspace-write`, `danger-full-access` | — |
| `--full-auto` | Full automation shortcut | — |
| `--search` | Enable live web search | — |
| `--oss` | Use a local open-source model | — |
| `--add-dir <path>` | Grant additional directory write access | — |
| `--cd <path>` / `-C` | Set working directory | Already handled by `cwd=REPO_DIR` |

### Configuration flags

| Flag | Description |
|------|-------------|
| `--config`/`-c KEY=VALUE` | Override config file values |
| `--profile`/`-p PROFILE` | Load a specific config profile |
| `--enable FEATURE` | Enable a feature flag |
| `--disable FEATURE` | Disable a feature flag |

---

## 4. Design Options

### Option 1 — Raw pass-through variable (Recommended)

A single env var per backend that appends arbitrary extra flags to the CLI invocation:

```env
COPILOT_EXTRA_ARGS=--allow-url github.com --add-dir /workspace --autopilot
CODEX_EXTRA_ARGS=--approval-mode full-auto --add-dir /workspace
```

**Implementation sketch** (`src/config.py`):
```python
class AIConfig(BaseSettings):
    copilot_extra_args: str = ""   # raw flags appended to copilot -p <prompt> ...
    codex_extra_args: str = ""     # raw flags appended to codex <prompt> ...
```

`src/ai/session.py` (`CopilotSession._build_cmd`):
```python
import shlex
args = ["copilot", "-p", prompt, "--allow-all"]
if self._model:
    args += ["--model", self._model]
if self._extra_args:
    args += shlex.split(self._extra_args)
return args
```

**Pros:**
- Zero maintenance: any future CLI flag works without code changes
- Operators have full control
- Single source of truth — the CLI docs are the documentation
- Clean and minimal implementation

**Cons:**
- No validation — bad flags fail silently at subprocess level
- Not discoverable from env var list alone; requires reading CLI docs

---

### Option 2 — Named common variables

Map frequently-used flags to named env vars:

```env
COPILOT_ALLOW_ALL_TOOLS=true
COPILOT_ALLOW_ALL_PATHS=true
COPILOT_ALLOW_ALL_URLS=true
COPILOT_AUTOPILOT=true
CODEX_APPROVAL_MODE=full-auto
CODEX_SANDBOX=workspace-write
```

**Pros:**
- Discoverable via `.env.example`
- Validated at startup (Pydantic coercion)
- Clear intent per variable

**Cons:**
- Every new useful flag requires a code + config change
- Flag names diverge between backends (Copilot vs Codex use different terminology)
- Creates ongoing maintenance burden

---

### Option 3 — Combination (named variables + pass-through)

Ship a small set of the most common named vars (e.g. `CODEX_APPROVAL_MODE`) and also provide `COPILOT_EXTRA_ARGS` / `CODEX_EXTRA_ARGS` for the long tail.

**Pros:** Best of both worlds — discoverability for common cases, flexibility for advanced ones

**Cons:** More surface area; named vars can conflict with pass-through (e.g. two `--approval-mode` flags)

---

### Option 4 — Other ideas

**4a. Single generic `CLI_EXTRA_ARGS` applied to whichever backend is active**

```env
CLI_EXTRA_ARGS=--allow-url api.example.com
```

Simpler but loses the per-backend specificity since Copilot and Codex flags are not interchangeable.

**4b. MCP config injection via env**

For Copilot specifically, MCP server configuration (`--additional-mcp-config`) could be exposed as a dedicated env var since it takes a JSON blob:

```env
COPILOT_MCP_CONFIG={"servers":{"my-mcp":{"command":"npx","args":["my-mcp-server"]}}}
```

Could be added on top of Option 1 as a convenience wrapper.

---

## 5. Recommendation

**Go with Option 1** (`COPILOT_EXTRA_ARGS` / `CODEX_EXTRA_ARGS`) as the primary mechanism.

Rationale:
- The container is already a trusted, isolated environment — operators are technical users who understand CLI flags
- The Copilot CLI flag surface is large and grows with each release; named variables would constantly lag behind
- `shlex.split()` safely handles quoting, so multi-word values work as expected
- A fix to the Codex `--approval-mode auto` bug (→ `full-auto`) should accompany this work

**Additionally fix the Codex approval mode bug** (`auto` → `full-auto`) as part of the same PR.

---

## 6. Implementation Plan

When approved, the work requires changes in these files:

| File | Change |
|------|--------|
| `src/config.py` | Add `copilot_extra_args: str = ""` and `codex_extra_args: str = ""` to `AIConfig` |
| `src/ai/session.py` | Accept `extra_args` in `CopilotSession.__init__`; append `shlex.split(extra_args)` in `_build_cmd` |
| `src/ai/copilot.py` | Pass `ai.copilot_extra_args` from config down to `CopilotSession` |
| `src/ai/codex.py` | Accept `extra_args`; append to cmd; **fix `auto` → `full-auto`** in `_make_cmd` |
| `src/ai/factory.py` | Pass `extra_args` fields when constructing backends |
| `.env.example` | Document `COPILOT_EXTRA_ARGS` and `CODEX_EXTRA_ARGS` with examples |
| `README.md` | Add new variables to the environment variable table |
| `tests/unit/test_session.py` | Tests for extra_args passthrough |
| `tests/unit/test_codex_backend.py` | Tests for extra_args passthrough + approval-mode fix |

Estimated scope: **small** — ~60 lines of production code + tests.

---

## 7. Open Questions

1. Should `COPILOT_EXTRA_ARGS` override or supplement the hardcoded `--allow-all`? (Recommendation: supplement — keep `--allow-all` as the default, extra args add to it.)
2. Should passing `--allow-all` remain hardcoded, or should it become the default value of `COPILOT_EXTRA_ARGS="--allow-all"`? Moving it to the default makes the variable truly the single source of truth.
3. For Codex: fix `--approval-mode auto` to `full-auto` as a separate patch, or include in this feature?
