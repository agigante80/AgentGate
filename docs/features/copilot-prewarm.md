# Copilot Conversation Pre-Warming (System Preamble Injection)

> Status: **Planned** | Priority: Low

Inject a static system-level context preamble into every Copilot prompt to reduce
repeated persona/context setup by users, and to give the AI a consistent identity
and project orientation on every call.

---

## ⚠️ Prerequisite Questions

> Answer these before writing a single line of code. A wrong assumption costs 10× more to fix than a clarification takes.

1. **Scope** — Both platforms. Preamble injection lives in `CopilotBackend`, which is called identically by both Telegram (`src/bot.py`) and Slack (`src/platform/slack.py`). No platform-specific changes are required.
2. **Backend** — `AI_CLI=copilot` **only**. Has no effect on `codex` or `api` backends. The feature is meaningless for stateful backends or direct-API backends that accept a proper `system` role.
3. **Stateful vs stateless** — Stateless only. `CopilotBackend.is_stateful = False`; preamble must be prepended on every individual call, not just once. No interaction with `CodexBackend`.
4. **Breaking change?** — No. `COPILOT_PREWARM=false` (default) is a strict no-op. All existing deployments are unaffected without setting the new env var.
5. **New dependency?** — No. Preamble injection is pure string manipulation. No new pip or npm package is required.
6. **Persistence** — No new DB table or file. The preamble is static config loaded at startup from `AIConfig`.
7. **Auth** — No new credential needed. Uses the existing `AI_CLI=copilot` GitHub Copilot authentication.
8. **`gate clear` interaction** — `clear_history()` must **not** reset the preamble. The preamble is operator config, not user conversation history. Confirm: preamble always comes back on the very next call after `gate clear`.

---

## Architectural Reality Check

> **⚠️ The original draft of this document contained several factual errors. This
> rewrite corrects them based on a thorough review of the current codebase.**

### How `CopilotBackend` actually works

- `CopilotBackend.is_stateful = False` (`src/ai/copilot.py`).
  This is the **opposite** of what the original document claimed.
- There is **no persistent PTY or interactive session**. `CopilotSession.send()` and
  `CopilotSession.stream()` both call `copilot -p <prompt> --allow-all` as a
  **fresh subprocess** on every single user message.
- Because it is stateless, the bot injects the last 10 history exchanges into every
  prompt via `history.build_context()` (called in `platform/common.py::build_prompt()`).
- The subprocess runs with `cwd=REPO_DIR` (`/repo`), so Copilot CLI already has full
  filesystem access to the cloned repository. It does **not** need explicit repo
  structure passed in — it can read it itself.

### What "pre-warming" means in this architecture

There is no session to warm. "Pre-warming" in this context means one of two things:

| Approach | What it does | Token cost |
|---|---|---|
| **A — System preamble** | Prepend a static persona/context string to _every_ prompt sent to `copilot -p` | Per-call (every message) |
| **B — Startup health check** | Run a trivial `copilot -p "ping"` at container start to verify the CLI works | Once at startup |

The original document conflated both and described neither accurately. This spec
covers **Approach A** as the primary feature, with **Approach B** as an optional
safety net.

---

## Problem Statement

When AgentGate is deployed with a team persona (e.g. `@GateCode`, `@GateSec` —
see `docs/features/multi-agent-slack.md`), every conversation starts blank from
Copilot's perspective. Users must repeatedly tell the AI who it is, what project
it is on, and what its behaviour guidelines are. This is:

- **Tedious**: every new chat or `gate clear` resets all persona context.
- **Inconsistent**: different users prompt persona differently, getting different AI
  behaviour from the same container.
- **Wasteful**: history-injected context eats token budget with boilerplate rather
  than useful exchanges.

---

## Proposed Solution: System Preamble Injection

Prepend a configurable preamble string to **every** prompt before it is passed to
`copilot -p`. The preamble is invisible to the user and is added in
`CopilotBackend.send()` and `CopilotBackend.stream()` before delegating to
`CopilotSession`.

### Example preamble

```
You are GateCode, an AI coding assistant for the AgentGate project.
You specialise in Python async code, Docker deployments, and Telegram/Slack bots.
Always respond concisely. Prefer code blocks over prose explanations.
```

The preamble is set once via env var; no runtime switching.

---

## Design

### New env vars

| Env var | Type | Default | Description |
|---|---|---|---|
| `COPILOT_PREWARM` | `bool` | `false` | Enable preamble injection |
| `COPILOT_PREWARM_PROMPT` | `str` | `""` | Preamble text. If empty and `COPILOT_PREWARM=true`, a built-in default is used |
| `COPILOT_PREWARM_HEALTHCHECK` | `bool` | `false` | Run a startup ping to verify CLI works before accepting user messages |

### Built-in default preamble (when `COPILOT_PREWARM=true` and no custom prompt set)

```
You are an AI coding assistant. Be concise and precise. Prefer code over prose.
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints specific to this feature.

- **`CopilotBackend.is_stateful = False`** (`src/ai/copilot.py`) — there is no persistent session. Every call to `send()` and `stream()` spawns a fresh `copilot -p` subprocess. The preamble must be prepended on _every_ call, not just the first one.
- **Inject in `CopilotBackend`, not `CopilotSession`** — `CopilotSession` is a low-level subprocess wrapper that must remain ignorant of persona config. Config-aware logic belongs in `CopilotBackend`. Never touch `CopilotSession` for this feature.
- **No platform-specific change needed** — both `src/bot.py` and `src/platform/slack.py` call the same `CopilotBackend`. The preamble injection is transparent to the platform layer.
- **Preamble vs. history ordering** — inject preamble _before_ the history context that `build_prompt()` in `platform/common.py` prepends. Runtime call order: `preamble + history_context + user_message`. If total prompt length is a concern, the preamble is the first thing to trim.
- **Field placement** — add `copilot_prewarm*` fields to `AIConfig`, not `BotConfig`. These are AI-provider-specific settings, not bot-behaviour settings.
- **`REPO_DIR` and `DB_PATH`** — not directly relevant to this feature; the preamble is a string in memory, not a file on disk.
- **`asyncio_mode = auto`** — all `async def test_*` functions in `tests/` run without `@pytest.mark.asyncio`.

---

## Implementation Steps

### Step 1 — `src/config.py`: add fields to `AIConfig`

```python
# In AIConfig:
copilot_prewarm: bool = False
copilot_prewarm_prompt: str = ""
copilot_prewarm_healthcheck: bool = False
```

No changes to `Settings.load()` — Pydantic reads env vars automatically.

### Step 2 — `src/ai/copilot.py`: inject preamble in `send()` and `stream()`

Add a `_preamble` attribute set in `__init__` from `AIConfig`, and prepend it:

```python
_DEFAULT_PREWARM = "You are an AI coding assistant. Be concise and precise. Prefer code over prose."

class CopilotBackend(AICLIBackend):
    is_stateful = False

    def __init__(self, model: str = "", opts: str = "", prewarm: bool = False, prewarm_prompt: str = "") -> None:
        ...
        if prewarm:
            self._preamble = (prewarm_prompt.strip() or _DEFAULT_PREWARM) + "\n\n"
        else:
            self._preamble = ""

    async def send(self, prompt: str) -> str:
        return await self._session.send(self._preamble + prompt)

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        async for chunk in self._session.stream(self._preamble + prompt):
            yield chunk
```

> **Why in `CopilotBackend` and not in `CopilotSession`?**
> `CopilotSession` is a low-level subprocess wrapper — it should not know about
> business-level persona config. Config-aware logic belongs in `CopilotBackend`.

### Step 3 — `src/ai/factory.py`: pass prewarm config

```python
if ai.ai_cli == "copilot":
    from src.ai.copilot import CopilotBackend
    return CopilotBackend(
        model=ai.ai_model,
        opts=ai.ai_cli_opts,
        prewarm=ai.copilot_prewarm,
        prewarm_prompt=ai.copilot_prewarm_prompt,
    )
```

### Step 4 (optional) — Startup health check in `src/main.py`

If `COPILOT_PREWARM_HEALTHCHECK=true`, call a trivial send after backend creation:

```python
if settings.ai.copilot_prewarm_healthcheck and settings.ai.ai_cli == "copilot":
    logger.info("Running Copilot CLI health check…")
    result = await backend.send("Respond with the word READY and nothing else.")
    if "READY" not in result.upper():
        logger.warning("Copilot health check unexpected response: %s", result[:200])
    else:
        logger.info("Copilot health check passed.")
```

This runs before the bot starts polling, so any CLI auth issues surface early with
a clear log message rather than silently failing on the first user message.

### Step 5 — Tests to write

New file: `tests/unit/test_copilot_backend.py`

| Test | What it checks |
|---|---|
| `test_prewarm_disabled_no_preamble` | `_preamble == ""` when `prewarm=False` |
| `test_prewarm_default_preamble` | `_preamble` contains default text when `prewarm=True, prewarm_prompt=""` |
| `test_prewarm_custom_preamble` | Custom prompt is used verbatim (plus `\n\n`) |
| `test_send_prepends_preamble` | Mock `CopilotSession.send`; assert call arg starts with preamble |
| `test_stream_prepends_preamble` | Mock `CopilotSession.stream`; assert call arg starts with preamble |
| `test_clear_history_preserves_preamble` | After `clear_history()`, `_preamble` is unchanged on new session |

Extend `tests/unit/test_config.py`:

| Test | What it checks |
|---|---|
| `test_copilot_prewarm_defaults` | `copilot_prewarm=False`, `copilot_prewarm_prompt=""`, `copilot_prewarm_healthcheck=False` |
| `test_copilot_prewarm_env_vars` | Env vars map correctly to `AIConfig` fields |

Extend `tests/integration/test_factory.py`:

| Test | What it checks |
|---|---|
| `test_factory_passes_prewarm_to_backend` | `create_backend()` with prewarm env vars yields a `CopilotBackend` with correct `_preamble` |

### Step 6 — Documentation updates

- `README.md`: add `COPILOT_PREWARM`, `COPILOT_PREWARM_PROMPT`, `COPILOT_PREWARM_HEALTHCHECK`
  to the environment variables reference table.
- `docker-compose.yml.example`: add commented-out `COPILOT_PREWARM` block under the
  Copilot section.
- `docs/features/multi-agent-slack.md`: update each agent's env block to show
  `COPILOT_PREWARM_PROMPT` with a persona-appropriate value.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add 3 new fields to `AIConfig`: `copilot_prewarm`, `copilot_prewarm_prompt`, `copilot_prewarm_healthcheck` |
| `src/ai/copilot.py` | **Edit** | Add `_preamble` attribute; prepend in `send()` and `stream()`; accept prewarm args via `__init__` |
| `src/ai/factory.py` | **Edit** | Pass prewarm config to `CopilotBackend()` constructor |
| `src/main.py` | **Edit** | Add optional startup health-check block (if `COPILOT_PREWARM_HEALTHCHECK=true`) |
| `README.md` | **Edit** | Add 3 env vars to the AI configuration table; add usage note for multi-agent persona |
| `docker-compose.yml.example` | **Edit** | Add commented-out `COPILOT_PREWARM` block under the Copilot section |
| `docs/features/multi-agent-slack.md` | **Edit** | Update each agent env block with a `COPILOT_PREWARM_PROMPT` example |
| `docs/features/copilot-prewarm.md` | **Edit** | Mark status as `Implemented` after merge to `main` |
| `docs/roadmap.md` | **Edit** | Mark item 2.9 as done (✅) |

**No changes to:**
- `src/ai/session.py` — `CopilotSession` must remain ignorant of persona config
- `src/bot.py` / `src/platform/slack.py` — preamble injection is transparent to the platform layer
- `src/ai/adapter.py` — `AICLIBackend.send()` signature is unchanged

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| None new | ✅ No new packages required | Preamble injection is pure string manipulation; no pip or npm additions needed |

> All required stdlib modules (`asyncio`, `logging`) are already imported in `copilot.py`.

---

## Test Plan

### `tests/unit/test_copilot_backend.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_prewarm_disabled_no_preamble` | `_preamble == ""` when `prewarm=False` |
| `test_prewarm_default_preamble` | `_preamble` contains the built-in default text when `prewarm=True, prewarm_prompt=""` |
| `test_prewarm_custom_preamble` | Custom prompt is used verbatim (with `\n\n` separator) |
| `test_send_prepends_preamble` | Mock `CopilotSession.send`; assert call arg starts with preamble |
| `test_stream_prepends_preamble` | Mock `CopilotSession.stream`; assert call arg starts with preamble |
| `test_clear_history_preserves_preamble` | After `clear_history()`, `_preamble` is unchanged on the new session |
| `test_empty_preamble_no_separator` | When `prewarm=False`, no extra `\n\n` is injected into the prompt |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_copilot_prewarm_defaults` | `copilot_prewarm=False`, `copilot_prewarm_prompt=""`, `copilot_prewarm_healthcheck=False` by default |
| `test_copilot_prewarm_env_vars` | All three env vars map correctly to `AIConfig` fields |

### `tests/integration/test_factory.py` additions

| Test | What it checks |
|------|----------------|
| `test_factory_passes_prewarm_to_backend` | `create_backend()` with prewarm env vars yields a `CopilotBackend` with the correct `_preamble` |
| `test_factory_prewarm_disabled_default` | Default env (no `COPILOT_PREWARM` set) yields `_preamble == ""` |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target: no uncovered branches in `CopilotBackend.__init__`, `send()`, and `stream()`. The healthcheck branch in `main.py` may use `# pragma: no cover` with a one-line explanation if it requires a live subprocess.

---

## Documentation Updates

### `README.md`

Add to the AI configuration environment variables table:

```markdown
| `COPILOT_PREWARM` | `false` | Prepend a static persona preamble to every Copilot prompt. Set `true` to enable. |
| `COPILOT_PREWARM_PROMPT` | `""` | Preamble text injected before each prompt. Leave empty to use the built-in default. Multi-line: use `\n` in `.env` files. |
| `COPILOT_PREWARM_HEALTHCHECK` | `false` | Run a startup ping (`copilot -p "READY"`) to verify the CLI is functional before accepting user messages. |
```

### `docker-compose.yml.example`

Add a commented block under the Copilot AI section:

```yaml
# Copilot preamble / persona injection (optional)
# COPILOT_PREWARM=true
# COPILOT_PREWARM_PROMPT=You are GateCode, a coding assistant for the AgentGate project.\nBe concise. Prefer code.
# COPILOT_PREWARM_HEALTHCHECK=false
```

### `docs/features/multi-agent-slack.md`

Update each agent's env block (`@GateCode`, `@GateSec`, `@GateDocs`) to include:

```yaml
COPILOT_PREWARM=true
COPILOT_PREWARM_PROMPT=You are GateCode, an AI coding assistant for AgentGate. Be concise. Prefer code.
```

### `.github/copilot-instructions.md`

No change needed — no new module or architectural pattern is introduced. The feature is a targeted addition to `CopilotBackend.__init__`, `send()`, and `stream()`.

### `docs/roadmap.md`

After merge to `main`, change item 2.9:

```markdown
| 2.9 | ✅ Copilot session pre-warming — inject persona preamble into every Copilot prompt | [→ features/copilot-prewarm.md](features/copilot-prewarm.md) |
```

---

## Token Cost Analysis

| Scenario | Extra tokens per message | Annual impact (100 msgs/day, 50-token preamble) |
|---|---|---|
| `COPILOT_PREWARM=false` (default) | 0 | 0 |
| `COPILOT_PREWARM=true`, default preamble (~12 tokens) | ~12 | ~438 000 tokens |
| `COPILOT_PREWARM=true`, rich persona (~100 tokens) | ~100 | ~3 650 000 tokens |

At GitHub Copilot free tier pricing (Premium request quota applies), keep the
preamble under 50 tokens for light usage. Rich personas should use `AI_CLI=api`
with a proper `system` parameter instead.

> **Design note**: If the preamble grows beyond ~200 tokens, it may be better to
> write it as a Copilot skills file (`COPILOT_SKILLS_DIRS`) rather than prompt
> injection. Skills files are read by the Copilot CLI natively and may be handled
> more efficiently than injected text.

---

## Pros and Cons

### Pros

- **Zero UX change**: users interact normally; preamble is transparent.
- **Consistent persona**: every message from every user gets the same baseline context.
- **No new dependencies**: pure string manipulation in one method.
- **Easily disableable**: `COPILOT_PREWARM=false` (default) is a strict no-op.
- **Per-deployment customisable**: each Docker container / agent can have its own persona.

### Cons

- **Token cost on every call**: unlike a stateful session where you pay once, stateless
  means the preamble is consumed on every single `copilot -p` invocation.
- **No runtime update**: changing `COPILOT_PREWARM_PROMPT` requires container restart.
- **Preamble ignored by history context**: the injected preamble is NOT stored in the
  SQLite history, so if `build_context()` produces a very long history, the preamble
  is prepended _before_ history, potentially making the total prompt very long.
- **May fight Copilot's own system prompt**: Copilot CLI has its own internal system
  prompt. A user preamble is injected as part of the user message, not as a true
  `system` role — Copilot may or may not honour persona instructions reliably.

---

## Alternatives Considered

| Alternative | Why not chosen |
|---|---|
| **Copilot skills file** (`COPILOT_SKILLS_DIRS`) | Already supported; this feature is complementary for dynamic/per-deployment text that shouldn't be a committed file |
| **True `system` role injection** | Not available in `copilot -p` CLI mode; would require API-mode (`AI_CLI=api`) |
| **Prepend preamble to history in SQLite** | Pollutes the DB; would re-appear in `gate history` and be included in every context window double-counted |
| **Custom `--instructions` Copilot flag** | No such flag in current Copilot CLI; may exist in future versions — worth watching |

---

## Open Questions

1. **Interaction with `gate clear`**: Should `clear_history()` also clear the preamble?
   No — the preamble is static config, not conversation history. `gate clear` should
   only clear SQLite history. The preamble always comes back on the next call.

2. **Multi-line preamble via env var**: Multi-line strings in env vars require `\n`
   escaping in `.env` files. Document this clearly with an example in README.

3. **Preamble vs Skills file precedence**: When both `COPILOT_SKILLS_DIRS` and
   `COPILOT_PREWARM_PROMPT` are set, what takes precedence? In practice they are
   additive (skills file is read by Copilot CLI, preamble is prepended to the prompt
   by AgentGate), but behaviour depends on how Copilot CLI handles overlapping
   instructions. Test with both set.

4. **Healthcheck timeout**: The startup health check should have its own timeout
   (suggest 30 s) separate from the per-message `TIMEOUT` in `session.py`. Use
   `asyncio.wait_for()` and log a warning (not a crash) on failure.

5. **Should `COPILOT_PREWARM_HEALTHCHECK` run on `clear_history()`?** When the user
   runs `gate clear`, `CopilotBackend.clear_history()` creates a new `CopilotSession`.
   Running a ping there would add latency. Recommend: startup only.

---

## Version Bump

Consult `docs/versioning.md` for the full decision guide. Quick reference:

| This feature… | Bump |
|---------------|------|
| Adds 3 new env vars with safe defaults (`COPILOT_PREWARM=false`) | **MINOR** |
| No existing env vars renamed or removed | Not MAJOR |
| Purely additive — no bug fix without user-visible API change | Not PATCH |

**Expected bump for this feature**: `MINOR` → `0.8.0` (from current `0.7.3`)

> Bump `VERSION` on `develop` _before_ the merge PR to `main`. Never edit `VERSION` directly on `main`.

---

## Roadmap Update

When this feature is complete, update `docs/roadmap.md` item **2.9**:

```markdown
| 2.9 | ✅ Copilot session pre-warming — inject persona preamble into every Copilot prompt | [→ features/copilot-prewarm.md](features/copilot-prewarm.md) |
```

No stretch goal identified at this time. The `COPILOT_SKILLS_DIRS` native skills-file approach is a complementary (not competing) mechanism and warrants a separate feature doc if needed.

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` is updated with the 3 new env vars.
- [ ] `docker-compose.yml.example` has the commented-out `COPILOT_PREWARM` block.
- [ ] `docs/roadmap.md` item 2.9 is marked done (✅).
- [ ] `docs/features/copilot-prewarm.md` status changed to `Implemented` on merge to `main`.
- [ ] `.github/copilot-instructions.md` is unchanged (no new module or architectural pattern).
- [ ] `VERSION` file bumped to `0.8.0` on `develop` before merge to `main`.
- [ ] `COPILOT_PREWARM=false` (default) produces zero behavioural change vs. current behaviour.
- [ ] `COPILOT_PREWARM=true` with a custom prompt: every single message to Copilot CLI starts with the preamble text.
- [ ] `gate clear` does **not** clear the preamble — preamble returns on the next call.
- [ ] Startup health check fires only when `COPILOT_PREWARM_HEALTHCHECK=true`, not otherwise.
- [ ] Feature is transparent on both **Telegram** and **Slack** — no platform-specific code paths.
- [ ] Feature is a strict no-op for `AI_CLI=codex` and `AI_CLI=api` deployments.
- [ ] Edge cases in the Open Questions section above are resolved and either handled or documented.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.


