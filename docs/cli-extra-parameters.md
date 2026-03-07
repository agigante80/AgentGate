# CLI Options — Design Document

> Status: **Planning**
> Branch: `develop`

This document analyses the design for exposing AI backend CLI options via a single TeleAgent environment variable (`AI_CLI_OPTS`). It covers the current state, a deep review of each backend's available options, critical trade-offs, and the recommended implementation plan.

---

## 1. Current State

### 1.1 Copilot CLI (`AI_CLI=copilot`)

Invocation in `src/ai/session.py`:

```python
args = ["copilot", "-p", prompt, "--allow-all"]
if self._model:
    args += ["--model", self._model]
```

**`--allow-all` is hardcoded.** It is equivalent to:
- `--allow-all-tools` — all tools run automatically without confirmation
- `--allow-all-paths` — file path verification disabled, any path accessible
- `--allow-all-urls` — all URLs accessible without confirmation

This gives Copilot **full authority** — no interactive permission prompts. The model is optionally configurable via `COPILOT_MODEL`.

### 1.2 Codex CLI (`AI_CLI=codex`)

Invocation in `src/ai/codex.py`:

```python
cmd = ["codex", prompt, "--approval-mode", "auto", "--model", self._model]
```

`--approval-mode auto` is hardcoded. However, valid approval mode values per Codex CLI docs are `suggest`, `auto-edit`, and `full-auto` — **`auto` is not a valid value** and may silently fall back to the default (`suggest`). The model is configurable via `CODEX_MODEL` (default: `o3`).

> ⚠️ **Bug**: `--approval-mode auto` must be fixed to `--approval-mode full-auto` as part of this work.

### 1.3 Direct API (`AI_CLI=api`)

No subprocess CLI involved — the Direct API backend calls OpenAI/Anthropic/Ollama APIs directly via Python SDK. CLI option concepts do not apply. `AI_CLI_OPTS` will be silently ignored (a warning will be logged at startup).

---

## 2. Copilot CLI — Available Options Deep Review

> Source: `copilot --help` (installed version: 0.0.421)

### Permission / authority flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--allow-all` | Enable all permissions (tools + paths + URLs) | **Currently hardcoded** |
| `--allow-all-tools` | Auto-run all tools without confirmation | Env: `COPILOT_ALLOW_ALL` (tools only) |
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
| `--max-autopilot-continues <n>` | Cap autopilot continuation steps | — |
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

### Copilot environment variables

| Env var | Equivalent flag |
|---------|----------------|
| `COPILOT_ALLOW_ALL` | `--allow-all-tools` only (not full `--allow-all`) |
| `GH_TOKEN` / `COPILOT_GITHUB_TOKEN` | Authentication token |

---

## 3. Codex CLI — Available Options Deep Review

> Source: OpenAI Codex CLI documentation (v0.111.0 as installed in Docker image)

### Approval / authority flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--approval-mode suggest` | Every file change and command needs manual approval | Default / safest |
| `--approval-mode auto-edit` | File edits auto-applied; commands need approval | — |
| `--approval-mode full-auto` | Files and commands fully automated | **Correct for headless** |
| `--full-auto` | Shortcut for `--approval-mode full-auto` | — |
| `--dangerously-bypass-approvals-and-sandbox` | No restrictions | ⚠️ Dangerous |
| `--yolo` | Alias for above | ⚠️ Dangerous |

### Model and execution flags

| Flag | Description | Notes |
|------|-------------|-------|
| `--model <model>` / `-m` | Model selection | **Configurable via `CODEX_MODEL`** |
| `--sandbox <mode>` | Sandboxing: `read-only`, `workspace-write`, `danger-full-access` | — |
| `--search` | Enable live web search | — |
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

## 4. Design: `AI_CLI_OPTS`

### 4.1 The variable

```env
AI_CLI_OPTS=           # default: empty — full-auto per backend (recommended for headless)
```

**Semantics:**

| `AI_CLI_OPTS` value | Copilot invocation | Codex invocation |
|---------------------|-------------------|-----------------|
| `""` (default / not set) | `copilot -p <prompt> --allow-all [--model ...]` | `codex <prompt> --approval-mode full-auto [--model ...]` |
| `--allow-url github.com --allow-all-tools` | `copilot -p <prompt> --allow-url github.com --allow-all-tools [--model ...]` | N/A (value is Copilot-specific) |
| `--approval-mode auto-edit` | N/A (Codex-specific) | `codex <prompt> --approval-mode auto-edit [--model ...]` |

**When `AI_CLI_OPTS` is non-empty, it replaces the full-auto defaults entirely.** The defaults are not preserved in the background.

### 4.2 Implementation sketch

`src/config.py` — `AIConfig`:
```python
ai_cli_opts: str = ""  # raw options appended to the CLI invocation; empty = full-auto per backend
```

`src/ai/session.py` — `CopilotSession._build_cmd`:
```python
import shlex

args = ["copilot", "-p", prompt]
if self._model:
    args += ["--model", self._model]
# Empty = apply full-auto defaults; non-empty = use as-is (replaces defaults)
extra = shlex.split(self._opts) if self._opts else ["--allow-all"]
args += extra
return args
```

`src/ai/codex.py` — `CodexBackend._make_cmd`:
```python
import shlex

extra = shlex.split(self._opts) if self._opts else ["--approval-mode", "full-auto"]
cmd = ["codex", prompt] + extra + ["--model", self._model]
return cmd
```

---

## 5. Critical Analysis

### 5.1 What this approach gets right

- **Minimal API surface** — one variable, one mental model
- **Zero maintenance** — every future CLI flag works without code changes
- **Backward compatible** — existing deployments with no `AI_CLI_OPTS` keep full-auto behaviour
- **Removes hardcoding** — full-auto defaults move from source code to documented config logic
- **Power-user friendly** — operators who know the CLI can set exactly what they need
- **Fixes the Codex bug** — `--approval-mode auto` → `full-auto` naturally as part of this work

### 5.2 Footguns and trade-offs

#### 🔴 Replacement, not additive

This is the biggest risk. `AI_CLI_EXTRA_ARGS` sounds like it *adds* to existing flags, but it *replaces* them entirely.

```env
# ❌ Operator intent: "add URL access on top of full-auto"
AI_CLI_OPTS=--allow-url github.com

# Result: Copilot starts WITHOUT --allow-all-tools
# → Every tool call blocks waiting for confirmation that never arrives
# → Bot appears to hang with no error message
```

The correct form:
```env
# ✅ Correct: include all required flags
AI_CLI_OPTS=--allow-all --allow-url github.com
```

> **Mitigation**: document this prominently in README and `.env.example`. Consider logging a startup warning if `AI_CLI_OPTS` is set for Copilot and does not contain `--allow-all-tools` or `--allow-all`.

#### 🟡 "OPTS" implies additive — consider the README wording carefully

The name `AI_CLI_OPTS` is accurate (these are the options passed to the CLI) but the zero-default pattern might still confuse: "if I don't set it, full-auto options are applied — if I do set it, they're removed." This must be front-loaded in documentation.

#### 🟡 Backend flag incompatibility

Copilot and Codex have different option names. Setting Copilot-specific opts and then switching to `AI_CLI=codex` (or vice-versa) will cause CLI errors:

```env
# Configured for Copilot
AI_CLI_OPTS=--allow-url github.com --allow-all-tools

# Then switching to Codex → codex rejects --allow-url, --allow-all-tools
AI_CLI=codex
```

> **Mitigation**: document in README that `AI_CLI_OPTS` must be re-evaluated when changing `AI_CLI`. No automatic validation is feasible since Copilot and Codex option namespaces are distinct.

#### 🟢 `AI_CLI=api` silently ignores `AI_CLI_OPTS`

The Direct API backend does not spawn a subprocess. Any `AI_CLI_OPTS` value is meaningless and will be silently ignored. This is acceptable but should produce a startup warning log to prevent operator confusion.

#### 🟢 Docker `.env` quoting for options with values

Values like `--allow-tool "shell(git:*)"` or `--additional-mcp-config '{...}'` require careful quoting. `shlex.split()` handles internal quoting correctly, but Docker Compose `.env` file parsing may strip or interpret quotes before the value reaches Python.

```env
# Potentially problematic in .env files
AI_CLI_OPTS=--allow-tool "shell(git:*)"

# Safer: use single quotes in the shell, or escape
AI_CLI_OPTS=--allow-tool 'shell(git:*)'
```

> Test complex values with `docker compose config` to verify the value survives Compose parsing.

### 5.3 Alternatives considered

| Alternative | Why not chosen |
|-------------|---------------|
| Per-backend vars (`COPILOT_OPTS` / `CODEX_OPTS`) | More config surface; but prevents the cross-backend flag confusion footgun described above. Still the right choice if the incompatibility issue becomes a real pain point. |
| Named common vars (`AI_CLI_ALLOW_ALL=true/false`) | Discoverable but requires code changes for every new flag; flags diverge between backends; ongoing maintenance burden. |
| Combination (named + pass-through) | More surface area; named vars can conflict with pass-through (two `--approval-mode` in same invocation). |

---

## 6. Implementation Plan

When approved, the following changes are required:

| File | Change |
|------|--------|
| `src/config.py` | Add `ai_cli_opts: str = ""` to `AIConfig` |
| `src/ai/session.py` | Read `opts` from config; if empty → `["--allow-all"]`; else `shlex.split(opts)` |
| `src/ai/copilot.py` | Pass `ai.ai_cli_opts` when constructing `CopilotSession` |
| `src/ai/codex.py` | Read `opts` from config; if empty → `["--approval-mode", "full-auto"]`; else `shlex.split(opts)`; **also fix `auto` → `full-auto` bug** |
| `src/ai/factory.py` | Pass `ai_cli_opts` field when constructing backends |
| `.env.example` | Document `AI_CLI_OPTS` with replacement semantics and examples |
| `README.md` | Add `AI_CLI_OPTS` to the environment variable table with prominent footgun warning |
| `tests/unit/test_session.py` | Test: empty opts → `["--allow-all"]`; non-empty → `shlex.split` result |
| `tests/unit/test_codex_backend.py` | Test: empty opts → `full-auto`; non-empty → as-is; `auto` bug is fixed |

Estimated scope: **small** — ~60 lines of production code + tests.

### Startup warning logic (recommended addition)

When `AI_CLI_OPTS` is set and `AI_CLI=api`:
```python
logger.warning("AI_CLI_OPTS is set but AI_CLI=api does not use a subprocess CLI; the value will be ignored.")
```

When `AI_CLI_OPTS` is set and `AI_CLI=copilot`, and the value does not contain `--allow-all-tools` or `--allow-all`:
```python
logger.warning("AI_CLI_OPTS is set for Copilot without --allow-all-tools. Tool calls may block waiting for confirmation.")
```

---

## 7. Decisions

| Question | Decision |
|----------|----------|
| Single var or per-backend vars? | **Single `AI_CLI_OPTS`** — simpler, one mental model |
| Additive or replacement semantics? | **Replacement** — empty default = full-auto; non-empty = verbatim (must include full-auto flags if desired) |
| Variable name? | **`AI_CLI_OPTS`** — matches Unix convention (`JAVA_OPTS`, `MAVEN_OPTS`); not "extra" to avoid additive implication |
| Fix Codex `auto` bug? | **Yes** — fix as part of this implementation; it's already broken |
| Startup warning for `AI_CLI=api`? | **Yes** — log a warning to help operators catch misconfiguration |
| Startup warning for missing `--allow-all-tools`? | **Yes** — log a warning for Copilot if `AI_CLI_OPTS` is set but lacks tool permissions |
