# API Key Scheme Refactor (`AI_API_KEY` removal)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-16

Replace the opaque `AI_API_KEY` master-fallback pattern with explicit, per-backend API
key variables. Each backend declares exactly which env var it requires; silent cross-backend
key re-use is eliminated.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/api-key-scheme.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Config and all three AI backends; both Telegram and Slack platforms.
2. **Backend** — All backends (`copilot`, `codex`, `api`, `gemini`). Copilot is unchanged (uses `COPILOT_GITHUB_TOKEN`).
3. **Stateful vs stateless** — Not affected; this is a config-layer change only.
4. **Breaking change?** — Yes. `AI_API_KEY` and `CODEX_API_KEY` are removed. **MAJOR** version bump required.
5. **New dependency?** — None.
6. **Persistence** — None. Env-var-only change.
7. **Auth** — This IS the auth change. See "Config Variables" for the new scheme.
8. **Deprecation window?** — One release with a startup warning before hard removal is recommended. Decided: emit a `DeprecationWarning` log if `AI_API_KEY` or `CODEX_API_KEY` are set in the environment, then ignore them.

---

## Problem Statement

1. **Silent key misrouting** — `AI_API_KEY` is silently passed to whichever backend is active. Switching `AI_CLI=codex` → `AI_CLI=api` with `AI_PROVIDER=anthropic` and only `AI_API_KEY` set passes an OpenAI key to Anthropic's SDK, producing a confusing 401 with no explanation.

2. **Opaque fallback chain** — `CODEX_API_KEY` falls back to `AI_API_KEY`; `WHISPER_API_KEY` falls back to `AI_API_KEY`. Neither is documented at the point of configuration (`.env` file). Users don't know which key is actually used at runtime.

3. **Naming inconsistency** — The Codex CLI subprocess is given `OPENAI_API_KEY` (the standard OpenAI env var), but AgentGate users set `CODEX_API_KEY` or `AI_API_KEY`. The mapping is hidden inside `factory.py`.

4. **Cannot scope billing** — There is no way to give the Codex backend a separate key (e.g. a project-scoped key) without the Whisper backend picking it up via the fallback.

5. **Future-proofing** — Every new backend (Gemini, Anthropic direct, etc.) must decide whether to add yet another fallback or break the chain. The fallback pattern does not scale.

---

## Current Behaviour (as of v0.22.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Config | `src/config.py` (`AIConfig`) | `ai_api_key: str = ""` — master fallback read from `AI_API_KEY` |
| Config | `src/config.py` (`CodexAIConfig`) | `codex_api_key: str = ""` — read from `CODEX_API_KEY`; falls back to `ai_api_key` |
| Config | `src/config.py` (`VoiceConfig`) | `whisper_api_key: str = ""` — falls back to `AIConfig.ai_api_key` at call-site |
| Factory | `src/ai/factory.py:55` | Passes `ai.ai_api_key` to `DirectAPIBackend` |
| Factory | `src/ai/factory.py:70` | `codex_key = ai.codex.codex_api_key or ai.ai_api_key` |
| Codex | `src/ai/codex.py:24` | Injects `codex_key` into subprocess as `OPENAI_API_KEY` |
| Transcriber | `src/transcriber.py:45,53` | `create_transcriber(config, fallback_api_key)` — caller passes `ai_api_key` as fallback |
| Secrets | `src/config.py` (`AIConfig.secret_values`) | Returns `[ai_api_key, codex.codex_api_key]` |

> **Key gap**: A single env var (`AI_API_KEY`) silently serves multiple incompatible backends. The fallback chain is invisible to the user and produces misleading auth errors on backend switches.

---

## Design Space

### Axis 1 — What to do with `AI_API_KEY`

#### Option A — Keep as optional fallback *(status quo)*

`AI_API_KEY` remains, backends still fall back to it.

**Pros:** Zero migration effort for existing users.

**Cons:** Perpetuates the confusion; the same problem recurs for every new backend.

---

#### Option B — Deprecate then remove *(recommended)*

In v1.0.0: emit a startup warning if `AI_API_KEY` or `CODEX_API_KEY` are detected in the environment, but still honour them. In v1.1.0: remove them entirely.

**Pros:** Smooth migration path; loud, actionable warning; clean end-state.

**Cons:** Two-release lag before the clean state.

---

#### Option C — Remove immediately (no deprecation)

**Pros:** Clean immediately.

**Cons:** Breaks every current deployment on upgrade with no warning.

**Recommendation: Option B** — one deprecation release provides a clear migration window without perpetuating the confusion beyond one more minor release.

---

### Axis 2 — `OPENAI_API_KEY` as the user-facing Codex key

#### Option A — New `CODEX_API_KEY` (keep separate name)

Keep `CODEX_API_KEY` but remove the `AI_API_KEY` fallback.

**Cons:** `CODEX_API_KEY` is a non-standard name; the Codex subprocess already uses `OPENAI_API_KEY`. Two different names for the same service causes confusion.

#### Option B — Use `OPENAI_API_KEY` directly *(recommended)*

The user sets `OPENAI_API_KEY`; AgentGate reads it and injects it into the subprocess under the same name. Aligns with every other OpenAI tool in the user's environment.

**Pros:** Standard; no mapping needed; removes `CODEX_API_KEY` entirely.

**Recommendation: Option B** — eliminates an invented alias with no upside.

---

### Axis 3 — DirectAPIBackend (`AI_CLI=api`) keys

#### Option A — Single `AI_API_KEY` (status quo)

**Cons:** An Anthropic key is not an OpenAI key. Silent failure when switching providers.

#### Option B — Provider-specific keys *(recommended)*

| `AI_PROVIDER` | Key to set |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `ollama` | _(none — local)_ |
| `openai-compat` | `OPENAI_API_KEY` (or custom base URL) |

**Pros:** Standard names (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`); fails loudly if the wrong key is set; aligns with SDK documentation.

**Recommendation: Option B** — each provider's standard name removes all ambiguity.

---

### Axis 4 — `WHISPER_API_KEY` fallback

#### Option A — Fall back to `OPENAI_API_KEY` (replace the old fallback)

Convenient, but recreates the same confusion: `OPENAI_API_KEY` serves two roles.

#### Option B — Explicit only *(recommended)*

If `WHISPER_PROVIDER=openai`, `WHISPER_API_KEY` **must** be set. No fallback.
`_validate_config()` raises `ValueError` with a clear message if it is missing.

**Pros:** Eliminates the second layer of implicit key sharing. Users who use a separate Whisper billing account (common) need this anyway.

**Recommendation: Option B** — explicit is always better for credentials.

---

## Recommended Solution

- **Axis 1**: Option B — deprecate `AI_API_KEY` / `CODEX_API_KEY` in v1.0.0; remove in v1.1.0.
- **Axis 2**: Option B — expose `OPENAI_API_KEY` as the user-facing Codex key.
- **Axis 3**: Option B — provider-specific keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) for `DirectAPIBackend`.
- **Axis 4**: Option B — `WHISPER_API_KEY` is explicit; no fallback.

### New key mapping (post-refactor)

| `AI_CLI` | Required env var | Notes |
|----------|-----------------|-------|
| `copilot` | `COPILOT_GITHUB_TOKEN` | External, managed by `gh auth`. Unchanged. |
| `codex` | `OPENAI_API_KEY` | AgentGate passes it into the Codex subprocess as-is. |
| `api` + `AI_PROVIDER=openai` | `OPENAI_API_KEY` | Used directly by the OpenAI SDK. |
| `api` + `AI_PROVIDER=anthropic` | `ANTHROPIC_API_KEY` | Used directly by the Anthropic SDK. |
| `api` + `AI_PROVIDER=ollama` | _(none)_ | Local service; no auth. |
| `api` + `AI_PROVIDER=openai-compat` | `OPENAI_API_KEY` | Custom base URL via `AI_BASE_URL`. |
| `gemini` | `GEMINI_API_KEY` | See `docs/features/gemini-cli-backend.md`. |
| Voice (`WHISPER_PROVIDER=openai`) | `WHISPER_API_KEY` | Explicit; no fallback. |

### Deprecation warning (v1.0.0 behaviour)

```python
import warnings, os

if os.environ.get("AI_API_KEY"):
    warnings.warn(
        "AI_API_KEY is deprecated and will be removed in v1.1.0. "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or the backend-specific key instead. "
        "See docs/features/api-key-scheme.md for the migration guide.",
        DeprecationWarning,
        stacklevel=2,
    )
if os.environ.get("CODEX_API_KEY"):
    warnings.warn(
        "CODEX_API_KEY is deprecated and will be removed in v1.1.0. "
        "Use OPENAI_API_KEY instead.",
        DeprecationWarning,
        stacklevel=2,
    )
```

Emit these in `Settings.load()` *after* all sub-configs are constructed so the check runs exactly once at startup.

---

## Architecture Notes

- **`secret_values()` protocol** — Every sub-config implements `secret_values() -> list[str]`. When adding `openai_api_key` / `anthropic_api_key` to `DirectAIConfig`, add both to its `secret_values()`. Remove `ai_api_key` and `codex_api_key` from `AIConfig.secret_values()`.
- **`_SECRET_ENV_KEYS` in `executor.py`** — Remove `AI_API_KEY` and `CODEX_API_KEY`; add `ANTHROPIC_API_KEY`. `OPENAI_API_KEY` and `GEMINI_API_KEY` are already present.
- **`create_transcriber()` signature** — Currently accepts `fallback_api_key: str = ""`. Remove this parameter; the function reads only `config.whisper_api_key`. The `_validate_config()` check in `main.py` ensures it is set when needed.
- **`_validate_config()` in `main.py`** — Add explicit validation: if `AI_CLI=api` and `AI_PROVIDER=openai`, require `OPENAI_API_KEY`; if `AI_PROVIDER=anthropic`, require `ANTHROPIC_API_KEY`. If `WHISPER_PROVIDER=openai`, require `WHISPER_API_KEY`.
- **`REPO_DIR` and `DB_PATH`** — unchanged; import from `src/config.py` as always.
- **Platform symmetry** — Changes are config/factory only. No platform-specific handler changes needed.
- **`asyncio_mode = auto`** — all `async def test_*` run without `@pytest.mark.asyncio`.

---

## Config Variables

### Removed (breaking)

| Env var | Removed in | Replacement |
|---------|-----------|-------------|
| `AI_API_KEY` | v1.1.0 (deprecated in v1.0.0) | `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` depending on backend |
| `CODEX_API_KEY` | v1.1.0 (deprecated in v1.0.0) | `OPENAI_API_KEY` |

### Added / formalised

| Env var | Sub-config | Default | Description |
|---------|-----------|---------|-------------|
| `OPENAI_API_KEY` | `DirectAIConfig` / `CodexAIConfig` | `""` | Required when `AI_CLI=codex` or `AI_CLI=api` + `AI_PROVIDER=openai/openai-compat`. |
| `ANTHROPIC_API_KEY` | `DirectAIConfig` | `""` | Required when `AI_CLI=api` + `AI_PROVIDER=anthropic`. |
| `WHISPER_API_KEY` | `VoiceConfig` | `""` | Required (explicit, no fallback) when `WHISPER_PROVIDER=openai`. |

> `GEMINI_API_KEY` is handled in `docs/features/gemini-cli-backend.md` — not duplicated here.

---

## Implementation Steps

### Step 1 — `src/config.py`: add `openai_api_key` and `anthropic_api_key`; remove `ai_api_key` and `codex_api_key`

```python
# In DirectAIConfig — add:
openai_api_key: str = ""   # OPENAI_API_KEY — for AI_PROVIDER=openai / openai-compat
anthropic_api_key: str = ""  # ANTHROPIC_API_KEY — for AI_PROVIDER=anthropic

def secret_values(self) -> list[str]:
    return [v for v in [self.openai_api_key, self.anthropic_api_key] if v]

# In CodexAIConfig — replace codex_api_key with:
openai_api_key: str = ""   # OPENAI_API_KEY — passed to Codex subprocess

def secret_values(self) -> list[str]:
    return [v for v in [self.openai_api_key] if v]

# In AIConfig — remove ai_api_key entirely; update secret_values():
def secret_values(self) -> list[str]:
    return []   # per-backend sub-configs declare their own secrets

# In VoiceConfig — remove fallback reference (field itself stays):
whisper_api_key: str = ""  # WHISPER_API_KEY — required when WHISPER_PROVIDER=openai; no fallback

# In Settings.load() — add deprecation warnings (see Recommended Solution above)
```

---

### Step 2 — `src/ai/factory.py`: route backends to their explicit keys

```python
# codex:
codex_key = ai.codex.openai_api_key
if not codex_key:
    raise ValueError("OPENAI_API_KEY must be set when AI_CLI=codex")

# api:
if ai.direct.ai_provider == "openai" or ai.direct.ai_provider == "openai-compat":
    api_key = ai.direct.openai_api_key
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set when AI_CLI=api and AI_PROVIDER=openai")
elif ai.direct.ai_provider == "anthropic":
    api_key = ai.direct.anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY must be set when AI_CLI=api and AI_PROVIDER=anthropic")
elif ai.direct.ai_provider == "ollama":
    api_key = ""   # no auth needed
```

---

### Step 3 — `src/transcriber.py`: remove `fallback_api_key` parameter

```python
# Before:
def create_transcriber(config: "VoiceConfig", fallback_api_key: str = "") -> Transcriber:
    api_key = config.whisper_api_key or fallback_api_key

# After:
def create_transcriber(config: "VoiceConfig") -> Transcriber:
    api_key = config.whisper_api_key
    if not api_key:
        raise ValueError("WHISPER_API_KEY must be set when WHISPER_PROVIDER=openai")
```

Update the two call-sites in `src/main.py` and `src/platform/slack.py` to remove the `fallback_api_key` argument.

---

### Step 4 — `src/executor.py`: update `_SECRET_ENV_KEYS`

```python
# Remove: "AI_API_KEY", "CODEX_API_KEY"
# Add: "ANTHROPIC_API_KEY"   (OPENAI_API_KEY and GEMINI_API_KEY already present)
_SECRET_ENV_KEYS: frozenset[str] = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "WHISPER_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "GITHUB_TOKEN",
    "COPILOT_GITHUB_TOKEN",
})
```

---

### Step 5 — `src/main.py`: update `_validate_config()` and `create_transcriber()` call

Add explicit provider/key validation:

```python
def _validate_config(settings: Settings) -> None:
    ai = settings.ai
    ...
    if ai.ai_cli == "codex" and not ai.codex.openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set when AI_CLI=codex")
    if ai.ai_cli == "api":
        if ai.direct.ai_provider in ("openai", "openai-compat") and not ai.direct.openai_api_key:
            raise ValueError("OPENAI_API_KEY must be set when AI_CLI=api and AI_PROVIDER=openai")
        if ai.direct.ai_provider == "anthropic" and not ai.direct.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set when AI_CLI=api and AI_PROVIDER=anthropic")
    voice = settings.voice
    if voice.whisper_provider == "openai" and not voice.whisper_api_key:
        raise ValueError("WHISPER_API_KEY must be set when WHISPER_PROVIDER=openai")
```

Remove `fallback_api_key` from `create_transcriber()` call.

---

### Step 6 — Tests: update mocks and assertions

- `tests/unit/test_bot.py` — remove references to `ai_api_key` and `codex_api_key` from `_make_settings()`.
- `tests/unit/test_config.py` (or create) — add tests for deprecation warnings and new `_validate_config()` checks.
- `tests/integration/test_factory.py` — update to pass `openai_api_key` / `anthropic_api_key`.
- `conftest.py` — update the autouse credential-scrub fixture to remove `AI_API_KEY` / `CODEX_API_KEY`; add `ANTHROPIC_API_KEY`.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Remove `ai_api_key` (AIConfig), `codex_api_key` (CodexAIConfig); add `openai_api_key` to CodexAIConfig, `openai_api_key` + `anthropic_api_key` to DirectAIConfig; add deprecation warnings in `Settings.load()` |
| `src/ai/factory.py` | **Edit** | Route each backend to its explicit key; raise `ValueError` if missing |
| `src/transcriber.py` | **Edit** | Remove `fallback_api_key` parameter; raise `ValueError` if `whisper_api_key` empty |
| `src/executor.py` | **Edit** | Remove `AI_API_KEY`, `CODEX_API_KEY` from `_SECRET_ENV_KEYS`; add `ANTHROPIC_API_KEY` |
| `src/main.py` | **Edit** | Extend `_validate_config()` with provider/key checks; update `create_transcriber()` call |
| `tests/unit/test_bot.py` | **Edit** | Remove `ai_api_key` / `codex_api_key` from `_make_settings()` helpers |
| `tests/unit/test_config.py` | **Create/Edit** | Tests for deprecation warnings; `_validate_config()` error cases |
| `tests/integration/test_factory.py` | **Edit** | Pass new key names in fixtures |
| `tests/conftest.py` | **Edit** | Update credential-scrub autouse fixture |
| `docs/features/gemini-cli-backend.md` | **Edit** | Remove `AI_API_KEY` fallback references |
| `README.md` | **Edit** | Update env var table; remove `AI_API_KEY`, `CODEX_API_KEY`; add `ANTHROPIC_API_KEY` |
| `.env.example` | **Edit** | Replace `AI_API_KEY` / `CODEX_API_KEY` with explicit per-backend vars |
| `docker-compose.yml.example` | **Edit** | Same as `.env.example` |
| `docs/roadmap.md` | **Edit** | Mark item done on completion |
| `docs/features/api-key-scheme.md` | **Edit** | Set status to `Implemented` on merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| _(none)_ | — | No new packages required. |

---

## Test Plan

### `tests/unit/test_config.py`

| Test | What it checks |
|------|----------------|
| `test_ai_api_key_deprecation_warning` | Setting `AI_API_KEY` env var triggers `DeprecationWarning` at `Settings.load()` |
| `test_codex_api_key_deprecation_warning` | Setting `CODEX_API_KEY` env var triggers `DeprecationWarning` |
| `test_validate_codex_requires_openai_key` | `AI_CLI=codex` with no `OPENAI_API_KEY` raises `ValueError` |
| `test_validate_api_openai_requires_key` | `AI_CLI=api` + `AI_PROVIDER=openai` with no `OPENAI_API_KEY` raises `ValueError` |
| `test_validate_api_anthropic_requires_key` | `AI_CLI=api` + `AI_PROVIDER=anthropic` with no `ANTHROPIC_API_KEY` raises `ValueError` |
| `test_validate_ollama_no_key_needed` | `AI_CLI=api` + `AI_PROVIDER=ollama` with no keys passes validation |
| `test_validate_whisper_requires_key` | `WHISPER_PROVIDER=openai` with no `WHISPER_API_KEY` raises `ValueError` |
| `test_secret_values_no_ai_api_key` | `AIConfig.secret_values()` no longer returns `AI_API_KEY` |
| `test_direct_config_secret_values` | `DirectAIConfig.secret_values()` returns `openai_api_key` and `anthropic_api_key` |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_make_settings_no_ai_api_key` | `_make_settings()` helper does not set `ai_api_key` |

### `tests/integration/test_factory.py`

| Test | What it checks |
|------|----------------|
| `test_factory_codex_uses_openai_key` | Factory passes `OPENAI_API_KEY` to Codex subprocess env |
| `test_factory_direct_openai_uses_openai_key` | Factory passes `OPENAI_API_KEY` to `DirectAPIBackend` |
| `test_factory_direct_anthropic_uses_anthropic_key` | Factory passes `ANTHROPIC_API_KEY` to `DirectAPIBackend` |

---

## Documentation Updates

### `README.md`

Replace the `AI_API_KEY` and `CODEX_API_KEY` rows in the env var table with:

| `OPENAI_API_KEY` | `""` | Required when `AI_CLI=codex` or `AI_CLI=api` + `AI_PROVIDER=openai`. Standard OpenAI env var. |
| `ANTHROPIC_API_KEY` | `""` | Required when `AI_CLI=api` + `AI_PROVIDER=anthropic`. Standard Anthropic env var. |
| `WHISPER_API_KEY` | `""` | Required (no fallback) when `WHISPER_PROVIDER=openai`. |

### `.env.example`

```bash
# AI backend key — set the one that matches your AI_CLI and AI_PROVIDER:
# OPENAI_API_KEY=sk-...       # for AI_CLI=codex or AI_CLI=api + AI_PROVIDER=openai
# ANTHROPIC_API_KEY=sk-ant-...  # for AI_CLI=api + AI_PROVIDER=anthropic
# GEMINI_API_KEY=AIza...       # for AI_CLI=gemini

# Voice transcription key (no fallback — must be set explicitly):
# WHISPER_API_KEY=sk-...       # required when WHISPER_PROVIDER=openai
```

### `docker-compose.yml.example`

Mirror the `.env.example` entries under the appropriate service block.

### `docs/roadmap.md`

Mark item 2.17 done (✅) when merged to `main`.

---

## Version Bump

This is a **MAJOR** version bump: `0.22.x` → `1.0.0`.

Rationale: `AI_API_KEY` and `CODEX_API_KEY` are removed (breaking). Any deployment using
either env var will fail at startup if not migrated.

The deprecation release (v1.0.0) still accepts the old vars but logs a startup warning.
The removal release (v1.1.0) drops them entirely and bumps to `1.1.0`.

---

## Roadmap Update

Add to `docs/roadmap.md`:

```markdown
| 2.17 | API key scheme refactor — explicit per-backend keys; remove AI_API_KEY master fallback | [→ features/api-key-scheme.md](features/api-key-scheme.md) |
```

---

## Migration Guide

> Include this section in `README.md` under a `## Upgrading from 0.x to 1.0` heading.

| Old env var | New env var | When |
|---|---|---|
| `AI_API_KEY` (used with `AI_CLI=codex`) | `OPENAI_API_KEY` | Always |
| `AI_API_KEY` (used with `AI_CLI=api` + `AI_PROVIDER=openai`) | `OPENAI_API_KEY` | Always |
| `AI_API_KEY` (used with `AI_CLI=api` + `AI_PROVIDER=anthropic`) | `ANTHROPIC_API_KEY` | Always |
| `CODEX_API_KEY` | `OPENAI_API_KEY` | Always |
| `WHISPER_API_KEY` falling back to `AI_API_KEY` | `WHISPER_API_KEY` (set it explicitly) | When using Whisper |

No other env vars change. Copilot and Gemini backends are unaffected.

---

## Edge Cases and Open Questions

1. **Existing deployments with only `AI_API_KEY` set** — The deprecation warning in v1.0.0 must surface clearly in container logs. `logger.warning()` (not `warnings.warn()`) is more visible in Docker log streams — use both.

2. **`AI_CLI=api` with no `AI_PROVIDER`** — Current default is `""`. Should we require `AI_PROVIDER` to be explicitly set? Proposed: yes — add validation that `AI_PROVIDER` is non-empty when `AI_CLI=api`. This is a separate but related cleanup.

3. **`openai-compat` provider** — Uses `OPENAI_API_KEY` but with a custom `AI_BASE_URL`. The key may be a non-OpenAI key (e.g. Azure). Is `OPENAI_API_KEY` the right name? Alternative: `COMPAT_API_KEY`. Decision deferred — `OPENAI_API_KEY` is widely understood and most compat endpoints accept it.

4. **Codex subprocess env** — `codex.py` currently injects the key as `OPENAI_API_KEY` into the subprocess. With the refactor the value comes from a field also named `openai_api_key`. The injection line stays identical — verify the env var name in the subprocess is still `OPENAI_API_KEY`, not the Python field name.

5. **`SecretRedactor` at runtime** — After removing `AI_API_KEY`, verify that `SecretRedactor._collect_secrets()` still gets all live key values. The collector iterates `secret_values()` on each sub-config — as long as `DirectAIConfig.secret_values()` returns both `openai_api_key` and `anthropic_api_key`, redaction is correct.

---

## Acceptance Criteria

- [ ] `AI_API_KEY` and `CODEX_API_KEY` in the environment produce a `DeprecationWarning` log line at startup (v1.0.0 behaviour).
- [ ] Setting `AI_CLI=codex` with no `OPENAI_API_KEY` raises `ValueError` with a clear message.
- [ ] Setting `AI_CLI=api` + `AI_PROVIDER=anthropic` with no `ANTHROPIC_API_KEY` raises `ValueError`.
- [ ] Setting `WHISPER_PROVIDER=openai` with no `WHISPER_API_KEY` raises `ValueError` (no fallback).
- [ ] `AIConfig.secret_values()` no longer returns the value of `AI_API_KEY`.
- [ ] `DirectAIConfig.secret_values()` returns `openai_api_key` and `anthropic_api_key`.
- [ ] `_SECRET_ENV_KEYS` in `executor.py` contains `ANTHROPIC_API_KEY` and does not contain `AI_API_KEY` or `CODEX_API_KEY`.
- [ ] `create_transcriber()` no longer accepts `fallback_api_key`.
- [ ] All existing tests pass with no failures (`pytest tests/ -v --tb=short`).
- [ ] `ruff check src/` reports no new issues.
- [ ] `README.md`, `.env.example`, `docker-compose.yml.example` updated.
- [ ] `docs/roadmap.md` entry 2.17 added.
- [ ] `VERSION` bumped to `1.0.0` on develop before merge to main.
