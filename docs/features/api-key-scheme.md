# API Key Scheme Refactor (`AI_API_KEY` removal)

> Status: **Approved** | Priority: High | Last reviewed: 2026-03-16

Replace the opaque `AI_API_KEY` master-fallback pattern with explicit, per-backend API
key variables. Each backend declares exactly which env var it requires; silent cross-backend
key re-use is eliminated.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/api-key-scheme.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 9/10 | 2026-03-16 | Fixed Step 3 call-sites (src/main.py → src/bot.py); added src/bot.py and src/platform/slack.py to Files table; clarified test_bot.py line 204/271 ai_api_key removals |
| GateSec  | 1 | 8/10 | 2026-03-16 | GateSec round 1: three security gaps — (1) `_collect_secrets()` blind spot for nested sub-config API keys (redaction leak), (2) `_SECRET_ENV_KEYS` uses wrong env var names (`TELEGRAM_BOT_TOKEN` / `GITHUB_TOKEN` instead of `TG_BOT_TOKEN` / `GITHUB_REPO_TOKEN`), (3) deprecation design says "still honour" old vars but implementation removes them outright; all three fixed inline |
| GateDocs | 1 | 9/10 | 2026-03-16 | Fixed Migration Guide heading inconsistency ("0.x to 1.0" → "v0.x to v1.0"); added AC items for GEMINI_API_KEY/GOOGLE_API_KEY/COPILOT_GITHUB_TOKEN and for two-PR split; flagged Open Question 2 for roadmap tracking |

**Status**: ✅ Approved — all round 2 scores ≥ 9/10
**Approved**: Yes — GateCode 9/10 | GateSec 9/10 | GateDocs 9/10 (round 2, 2026-03-16)

### Round 1 blocking gaps (for round 2 addressal)

GateSec's 8/10 indicates unresolved security concerns after the inline fixes. The following gaps remain open for GateSec to resolve in round 2 — implementers and reviewers should consult the doc for full details:

- _Secret collector coverage_ — `SecretRedactor._collect_secrets()` only traverses top-level `Settings` fields; nested sub-configs (`DirectAIConfig`, `CodexAIConfig`) are not reached. `AIConfig.secret_values()` must delegate to its nested sub-configs (see Architecture Notes). A unit test asserting this delegation is required (see Test Plan). The Architecture Notes section documents the fix; verify the test plan covers it end-to-end.
- _`_SECRET_ENV_KEYS` name correctness_ — Any change to the set must preserve `TG_BOT_TOKEN` and `GITHUB_REPO_TOKEN` exactly. A regression here causes `scrubbed_env()` to silently stop filtering those tokens. The AC now includes an explicit checkbox; the test `test_secret_env_keys_correct_names` must be extended to also assert absence of renamed variants.
- _Two-PR implementation split_ — The deprecation design (warn + keep in v1.0.0; hard removal in v1.1.0) must be enforced at the PR level. A single PR delivering hard removal in v1.0.0 is a breaking change with no migration window. The AC now includes a checkbox for this split.

### Round 2 pending

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 2 | 9/10 | 2026-03-16 | Split Step 1 into PR1/PR2 sub-steps; labelled all Steps PR1 or PR2; fixed executor.py Files table (missing GEMINI_API_KEY, GOOGLE_API_KEY, COPILOT_GITHUB_TOKEN); added Step 7 for .github/copilot-instructions.md; resolved Open Question 2 (deferred, roadmap item 2.18 added); sharpened test_secret_env_keys_correct_names to assert absence of wrong names |
| GateSec  | 2 | 9/10 | 2026-03-16 | All three round 1 blocking gaps resolved: (1) `_collect_secrets()` delegation — Step 1b, test, and AC all correct; (2) `_SECRET_ENV_KEYS` names — Step 4 uses correct names, test asserts absence of wrong ones; (3) two-PR split — Steps labelled PR1/PR2, AC enforces it. One minor fix: `conftest.py` `clean_env` must also scrub `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` (promoted to Pydantic fields by the refactor); added to Step 6, Files table, and AC |
| GateDocs | 2 | 9/10 | 2026-03-16 | Fixed Version Bump rationale (v1.0.0 is non-breaking; clarified intentional SemVer deviation for v1.1.0); added inline import note to Step 1a; added tracking note to Open Question 3 |

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
import logging, warnings, os

logger = logging.getLogger(__name__)

if os.environ.get("AI_API_KEY"):
    _msg = (
        "AI_API_KEY is deprecated and will be removed in v1.1.0. "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or the backend-specific key instead. "
        "See docs/features/api-key-scheme.md for the migration guide."
    )
    logger.warning(_msg)          # visible in Docker log streams
    warnings.warn(_msg, DeprecationWarning, stacklevel=2)

if os.environ.get("CODEX_API_KEY"):
    _msg = (
        "CODEX_API_KEY is deprecated and will be removed in v1.1.0. "
        "Use OPENAI_API_KEY instead."
    )
    logger.warning(_msg)
    warnings.warn(_msg, DeprecationWarning, stacklevel=2)
```

Emit these in `Settings.load()` *after* all sub-configs are constructed so the check runs exactly once at startup. Using both `logger.warning()` and `warnings.warn()` ensures the message is visible in Docker log streams (where Python `warnings` output is often suppressed) as well as in test suites that check for `DeprecationWarning`.

---

## Architecture Notes

- **`secret_values()` protocol** — Every sub-config implements `secret_values() -> list[str]`. When adding `openai_api_key` / `anthropic_api_key` to `DirectAIConfig`, add both to its `secret_values()`. **Critical: `SecretRedactor._collect_secrets()` only iterates top-level `Settings` fields** (telegram, slack, github, bot, ai, voice, audit, storage). `DirectAIConfig` and `CodexAIConfig` are _nested_ inside `AIConfig` (accessed as `settings.ai.direct` / `settings.ai.codex`), so their `secret_values()` methods will never be called by the collector. Setting `AIConfig.secret_values()` to `return []` would silently drop all API key values from redaction, leaking `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in AI responses and shell output. **Fix: `AIConfig.secret_values()` must delegate** to its nested sub-configs:
  ```python
  # AIConfig.secret_values() — post-refactor
  def secret_values(self) -> list[str]:
      return self.direct.secret_values() + self.codex.secret_values()
  ```
  This preserves the existing pattern (today `AIConfig` already manually includes `self.codex.codex_api_key`) without modifying `_collect_secrets()` or `_KNOWN_SUBCONFIGS`.
- **`_SECRET_ENV_KEYS` in `executor.py`** — Remove `AI_API_KEY` and `CODEX_API_KEY`; add `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `COPILOT_GITHUB_TOKEN`. `OPENAI_API_KEY` is already present. **Use the actual env var names from `src/config.py`**: `TG_BOT_TOKEN` (not `TELEGRAM_BOT_TOKEN`) and `GITHUB_REPO_TOKEN` (not `GITHUB_TOKEN`). Using the wrong names would cause `scrubbed_env()` to stop filtering those tokens, leaking them into subprocess environments.
- **`create_transcriber()` signature** — Currently accepts `fallback_api_key: str = ""`. Remove this parameter; the function reads only `config.whisper_api_key`. The `_validate_config()` check in `main.py` ensures it is set when needed.
- **`_validate_config()` in `main.py`** — Add explicit validation: if `AI_CLI=api` and `AI_PROVIDER=openai`, require `OPENAI_API_KEY`; if `AI_PROVIDER=anthropic`, require `ANTHROPIC_API_KEY`. If `WHISPER_PROVIDER=openai`, require `WHISPER_API_KEY`.
- **Deprecation vs removal: implementation must match design** — Axis 1 Option B says v1.0.0 "still honours" `AI_API_KEY`/`CODEX_API_KEY` (deprecation warning only), with hard removal in v1.1.0. However, the implementation steps (Step 1) remove the config fields and Step 2 removes the fallback logic, making v1.0.0 a _hard break_ not a graceful deprecation. **Reconciliation:** either (a) keep the config fields readable in v1.0.0 with fallback logic intact and emit the deprecation warning, deferring the field removal to v1.1.0; or (b) change the design to say v1.0.0 _removes_ them outright (effectively Option C). Recommended: Option (a) — the deprecation warning gives operators time to update `.env` files without downtime. This means `ai_api_key` and `codex_api_key` _stay_ in config for v1.0.0; only the deprecation check is added. Two separate implementation PRs (v1.0.0 = warn + still work; v1.1.0 = remove fields + break).
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

> **⚠️ Two-PR delivery required** (see AC and Architecture Notes).
>
> - **PR 1 (v1.0.0)** — add deprecation warnings; all existing fields and fallback logic remain intact. Users see the warning but experience no breakage.
> - **PR 2 (v1.1.0)** — remove deprecated fields and fallback logic; add new explicit fields. Hard break for un-migrated deployments.
>
> Steps below are labelled `[PR1]` or `[PR2]` where the split matters. A step labelled `[PR2]` must not appear in the PR1 merge.

### Step 1 — `src/config.py`

**Step 1a \[PR1\]** — add deprecation warnings in `Settings.load()` only; all existing fields (`ai_api_key`, `codex_api_key`) remain:

```python
# In Settings.load() — add immediately after all sub-configs are constructed.
# Note: move these imports to module level in the actual implementation;
# they are shown inline here for self-contained readability only.
import logging, warnings, os as _os

_log = logging.getLogger(__name__)
if _os.environ.get("AI_API_KEY"):
    _msg = (
        "AI_API_KEY is deprecated and will be removed in v1.1.0. "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or the backend-specific key instead. "
        "See docs/features/api-key-scheme.md for the migration guide."
    )
    _log.warning(_msg)
    warnings.warn(_msg, DeprecationWarning, stacklevel=2)
if _os.environ.get("CODEX_API_KEY"):
    _msg = (
        "CODEX_API_KEY is deprecated and will be removed in v1.1.0. "
        "Use OPENAI_API_KEY instead."
    )
    _log.warning(_msg)
    warnings.warn(_msg, DeprecationWarning, stacklevel=2)
```

**Step 1b \[PR2\]** — add new explicit fields; remove `ai_api_key` and `codex_api_key`; update `secret_values()` delegation:

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

# In AIConfig — remove ai_api_key; delegate to nested sub-configs (see Architecture Notes):
def secret_values(self) -> list[str]:
    return self.direct.secret_values() + self.codex.secret_values()

# In VoiceConfig — remove fallback reference (field itself stays):
whisper_api_key: str = ""  # WHISPER_API_KEY — required when WHISPER_PROVIDER=openai; no fallback
```

---

### Step 2 — `src/ai/factory.py`: route backends to their explicit keys \[PR2\]

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

### Step 3 — `src/transcriber.py`: remove `fallback_api_key` parameter \[PR2\]

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

Update the two call-sites — `src/bot.py` (Telegram) and `src/platform/slack.py` (Slack) — to remove the `fallback_api_key` argument. (`src/main.py` does not call `create_transcriber()` directly; both bots call it independently in their startup paths.)

---

### Step 4 — `src/executor.py`: update `_SECRET_ENV_KEYS` \[PR2\]

```python
# Remove: "AI_API_KEY", "CODEX_API_KEY"
# Add: "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "COPILOT_GITHUB_TOKEN"
# Keep existing names unchanged — TG_BOT_TOKEN and GITHUB_REPO_TOKEN are the correct
# env var names used in src/config.py (not TELEGRAM_BOT_TOKEN / GITHUB_TOKEN).
_SECRET_ENV_KEYS: frozenset[str] = frozenset({
    "TG_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "GITHUB_REPO_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "WHISPER_API_KEY",
    "COPILOT_GITHUB_TOKEN",
})
```

---

### Step 5 — `src/main.py`: update `_validate_config()` \[PR2\]

Add explicit provider/key validation (validation only — `src/main.py` does not call `create_transcriber()` directly):

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

> `create_transcriber()` is called in `src/bot.py` (Telegram) and `src/platform/slack.py` (Slack) — see Step 3.

---

### Step 6 — Tests: update mocks and assertions \[PR2\]

- `tests/unit/test_bot.py` — remove references to `ai_api_key` and `codex_api_key` from `_make_settings()`.
- `tests/unit/test_config.py` (or create) — add tests for deprecation warnings and new `_validate_config()` checks.
- `tests/integration/test_factory.py` — update to pass `openai_api_key` / `anthropic_api_key`.
- `conftest.py` — update the autouse credential-scrub fixture to remove `AI_API_KEY` / `CODEX_API_KEY`; add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and `GOOGLE_API_KEY`. `OPENAI_API_KEY` is critical: the refactor promotes it from "injected into a subprocess env" to a first-class Pydantic config field read by both `DirectAIConfig` and `CodexAIConfig` — without scrubbing it, a developer's shell-level key leaks into every test run.

---

### Step 7 — `.github/copilot-instructions.md` \[PR2\]

Update the key-naming notes in the instructions file to:
- Document the new per-backend scheme (`OPENAI_API_KEY` for codex/api+openai, `ANTHROPIC_API_KEY` for api+anthropic, `GEMINI_API_KEY` for gemini, `WHISPER_API_KEY` for voice — no fallbacks).
- Note that `AI_API_KEY` and `CODEX_API_KEY` are removed as of v1.1.0.
- Confirm the `secret_values()` convention still applies; remind that `AIConfig.secret_values()` must delegate to nested sub-configs.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Remove `ai_api_key` (AIConfig), `codex_api_key` (CodexAIConfig); add `openai_api_key` to CodexAIConfig, `openai_api_key` + `anthropic_api_key` to DirectAIConfig; add deprecation warnings in `Settings.load()` |
| `src/ai/factory.py` | **Edit** | Route each backend to its explicit key; raise `ValueError` if missing |
| `src/transcriber.py` | **Edit** | Remove `fallback_api_key` parameter; raise `ValueError` if `whisper_api_key` empty |
| `src/executor.py` | **Edit** | Remove `AI_API_KEY`, `CODEX_API_KEY` from `_SECRET_ENV_KEYS`; add `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `COPILOT_GITHUB_TOKEN` |
| `src/main.py` | **Edit** | Extend `_validate_config()` with provider/key checks (no `create_transcriber` call here) |
| `src/bot.py` | **Edit** | Remove `fallback_api_key=settings.ai.ai_api_key` from `create_transcriber()` call (line 262) |
| `src/platform/slack.py` | **Edit** | Remove `fallback_api_key=settings.ai.ai_api_key` from `create_transcriber()` call (line 119) |
| `tests/unit/test_bot.py` | **Edit** | Remove `ai_api_key` / `codex_api_key` from `_make_settings()` helpers |
| `tests/unit/test_config.py` | **Create/Edit** | Tests for deprecation warnings; `_validate_config()` error cases |
| `tests/integration/test_factory.py` | **Edit** | Pass new key names in fixtures |
| `tests/conftest.py` | **Edit** | Update credential-scrub autouse fixture: remove `AI_API_KEY`/`CODEX_API_KEY`; add `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| `docs/features/gemini-cli-backend.md` | **Edit** | Remove `AI_API_KEY` fallback references |
| `README.md` | **Edit** | Update env var table; remove `AI_API_KEY`, `CODEX_API_KEY`; add `ANTHROPIC_API_KEY` |
| `.env.example` | **Edit** | Replace `AI_API_KEY` / `CODEX_API_KEY` with explicit per-backend vars |
| `docker-compose.yml.example` | **Edit** | Same as `.env.example` |
| `docs/roadmap.md` | **Edit** | Mark item done on completion |
| `docs/features/api-key-scheme.md` | **Edit** | Set status to `Implemented` on merge |
| `.github/copilot-instructions.md` | **Edit** | Update key-naming notes: document new per-backend scheme (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), note that `AI_API_KEY`/`CODEX_API_KEY` are removed, and confirm `secret_values()` convention still applies |

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
| `test_ai_config_delegates_to_nested_secrets` | `AIConfig.secret_values()` includes values from `DirectAIConfig.secret_values()` and `CodexAIConfig.secret_values()` — ensures `SecretRedactor._collect_secrets()` discovers per-backend keys |
| `test_direct_config_secret_values` | `DirectAIConfig.secret_values()` returns `openai_api_key` and `anthropic_api_key` |
| `test_secret_env_keys_correct_names` | `_SECRET_ENV_KEYS` contains `TG_BOT_TOKEN` and `GITHUB_REPO_TOKEN`; explicitly asserts `TELEGRAM_BOT_TOKEN` and `GITHUB_TOKEN` are NOT present (absence of wrong names); also asserts `ANTHROPIC_API_KEY` is present |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_make_settings_no_ai_api_key` | `_make_settings()` helper does not set `ai_api_key` |

> Also remove the two existing `settings.ai.ai_api_key = "sk-test"` assignments (lines 204 and 271) and replace with the appropriate per-backend key (`settings.ai.direct.openai_api_key` etc.) depending on what each test exercises.

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

Add a `## Upgrading from v0.x to v1.0` section (place before the Changelog or at the end of the README). This section must include:

1. The migration table from the [Migration Guide](#migration-guide) section below.
2. A note about the startup warning message — self-hosters using the old vars will see this in their container logs:
   ```
   WARNING: AI_API_KEY is deprecated and will be removed in v1.1.0. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or the backend-specific key instead. See docs/features/api-key-scheme.md for the migration guide.
   ```
   Without this note, operators may not know the warning is actionable or how to respond to it.

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

Rationale: The v1.0.0 release initiates the breaking migration cycle — the API key scheme changes fundamentally and operators must act before v1.1.0. The MAJOR bump is taken at the *start* of this cycle to signal the change clearly, even though v1.0.0 itself is non-breaking (old vars are still accepted with a warning).

> **SemVer note:** v1.1.0 (hard removal) is technically also a breaking change and would warrant a second MAJOR bump under strict SemVer. The project opts for a MINOR increment within the 1.x line to avoid a v2.0.0 one release after v1.0.0. This is a deliberate project convention, not an oversight.

The deprecation release (v1.0.0) still accepts the old vars but logs a startup warning.
The removal release (v1.1.0) drops them entirely and bumps to `1.1.0`.

---

## Roadmap Update

Item 2.17 already exists in `docs/roadmap.md`. When this feature is merged to `main`, replace the existing row with the ✅-marked version:

```markdown
| 2.17 | ✅ API key scheme refactor — explicit per-backend keys; remove `AI_API_KEY` master fallback | [→ features/api-key-scheme.md](features/api-key-scheme.md) |
```

> Do not add a new row — the item already appears in the roadmap. Editing in place preserves the table's sequential ordering.

---

## Migration Guide

> Include this section in `README.md` under a `## Upgrading from v0.x to v1.0` heading.

| Old env var | New env var | When |
|---|---|---|
| `AI_API_KEY` (used with `AI_CLI=codex`) | `OPENAI_API_KEY` | Always |
| `AI_API_KEY` (used with `AI_CLI=api` + `AI_PROVIDER=openai`) | `OPENAI_API_KEY` | Always |
| `AI_API_KEY` (used with `AI_CLI=api` + `AI_PROVIDER=anthropic`) | `ANTHROPIC_API_KEY` | Always |
| `CODEX_API_KEY` | `OPENAI_API_KEY` | Always |
| `WHISPER_API_KEY` falling back to `AI_API_KEY` | `WHISPER_API_KEY` (set it explicitly) | If you previously omitted `WHISPER_API_KEY` and relied on `AI_API_KEY` as a silent fallback — the fallback is gone; you must now set `WHISPER_API_KEY` explicitly |

No other env vars change. Copilot and Gemini backends are unaffected.

---

## Edge Cases and Open Questions

1. **Existing deployments with only `AI_API_KEY` set** — The deprecation warning in v1.0.0 must surface clearly in container logs. `logger.warning()` (not `warnings.warn()`) is more visible in Docker log streams — use both.

2. **`AI_CLI=api` with no `AI_PROVIDER`** — Current default is `""`. Should we require `AI_PROVIDER` to be explicitly set? Proposed: yes — add validation that `AI_PROVIDER` is non-empty when `AI_CLI=api`. This is a separate but related cleanup. _GateDocs note: if this is in scope for this feature, add an AC item and a row to the Files to Change table for `_validate_config()`; if deferred, add a roadmap item (suggested: 2.18) so it is not lost._ **Decision (round 2): deferred — out of scope for this feature. Tracked as roadmap item 2.18 (`AI_PROVIDER` explicit-required validation). No AC item added here.**

3. **`openai-compat` provider** — Uses `OPENAI_API_KEY` but with a custom `AI_BASE_URL`. The key may be a non-OpenAI key (e.g. Azure). Is `OPENAI_API_KEY` the right name? Alternative: `COMPAT_API_KEY`. Decision deferred — `OPENAI_API_KEY` is widely understood and most compat endpoints accept it. _GateDocs note: if Azure AD token auth or a dedicated `COMPAT_API_KEY` is needed in future, it should be tracked as a separate roadmap item rather than reopening this feature. Suggested: 2.19._

4. **Codex subprocess env** — `codex.py` currently injects the key as `OPENAI_API_KEY` into the subprocess. With the refactor the value comes from a field also named `openai_api_key`. The injection line stays identical — verify the env var name in the subprocess is still `OPENAI_API_KEY`, not the Python field name.

5. **`SecretRedactor` at runtime** — ~~After removing `AI_API_KEY`, verify that `SecretRedactor._collect_secrets()` still gets all live key values. The collector iterates `secret_values()` on each sub-config — as long as `DirectAIConfig.secret_values()` returns both `openai_api_key` and `anthropic_api_key`, redaction is correct.~~ **Resolved (GateSec round 1):** `_collect_secrets()` only iterates _top-level_ `Settings` fields. `DirectAIConfig` and `CodexAIConfig` are nested under `AIConfig`, so their `secret_values()` will never be called directly. `AIConfig.secret_values()` must delegate to its nested sub-configs (see Architecture Notes). A unit test must confirm that `SecretRedactor._collect_secrets()` returns the new per-backend key values after the refactor.

6. **`_SECRET_ENV_KEYS` env var names** (GateSec round 1) — The current codebase uses `TG_BOT_TOKEN` and `GITHUB_REPO_TOKEN` (not `TELEGRAM_BOT_TOKEN` / `GITHUB_TOKEN`). Any change to `_SECRET_ENV_KEYS` must preserve the existing names exactly. Using the wrong names causes `scrubbed_env()` to stop filtering those tokens, leaking them into every subprocess. The implementer should diff the final set against the current one to confirm only the intended additions/removals occurred.

7. **Deprecation timeline vs implementation scope** (GateSec round 1) — The Axis 1 design recommends Option B (deprecate in v1.0.0, remove in v1.1.0) but the implementation steps remove config fields and fallback logic immediately, which is effectively Option C (hard removal). The implementation must be split into two PRs matching the two-release plan, or the design must be revised to say v1.0.0 removes them outright. See Architecture Notes for details.

---

## Acceptance Criteria

- [ ] `AI_API_KEY` and `CODEX_API_KEY` in the environment produce a `DeprecationWarning` log line at startup (v1.0.0 behaviour).
- [ ] Setting `AI_CLI=codex` with no `OPENAI_API_KEY` raises `ValueError` with a clear message.
- [ ] Setting `AI_CLI=api` + `AI_PROVIDER=anthropic` with no `ANTHROPIC_API_KEY` raises `ValueError`.
- [ ] Setting `WHISPER_PROVIDER=openai` with no `WHISPER_API_KEY` raises `ValueError` (no fallback).
- [ ] `AIConfig.secret_values()` no longer returns the value of `AI_API_KEY`.
- [ ] `AIConfig.secret_values()` delegates to `self.direct.secret_values() + self.codex.secret_values()` so that `SecretRedactor._collect_secrets()` (which only iterates top-level `Settings` fields) still discovers all API key values.
- [ ] `DirectAIConfig.secret_values()` returns `openai_api_key` and `anthropic_api_key`.
- [ ] `_SECRET_ENV_KEYS` in `executor.py` contains `ANTHROPIC_API_KEY` and does not contain `AI_API_KEY` or `CODEX_API_KEY`.
- [ ] `_SECRET_ENV_KEYS` contains `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and `COPILOT_GITHUB_TOKEN` (all added in Step 4; absence would leak these values into subprocess environments).
- [ ] `_SECRET_ENV_KEYS` preserves `TG_BOT_TOKEN` and `GITHUB_REPO_TOKEN` (the actual env var names — not `TELEGRAM_BOT_TOKEN` / `GITHUB_TOKEN`).
- [ ] `create_transcriber()` no longer accepts `fallback_api_key`.
- [ ] Implementation is delivered as two separate PRs: PR 1 (v1.0.0) adds deprecation warnings and keeps `AI_API_KEY`/`CODEX_API_KEY` functional; PR 2 (v1.1.0) removes the fields and fallback logic. A single PR that removes fields in v1.0.0 violates the Axis 1 design and turns Option B into Option C.
- [ ] All existing tests pass with no failures (`pytest tests/ -v --tb=short`).
- [ ] `ruff check src/` reports no new issues.
- [ ] `README.md`, `.env.example`, `docker-compose.yml.example` updated (including `## Upgrading from v0.x to v1.0` section with migration table and startup warning message).
- [ ] `docs/roadmap.md` entry 2.17 marked ✅.
- [ ] `.github/copilot-instructions.md` updated to reflect the new per-backend key scheme and removal of `AI_API_KEY` / `CODEX_API_KEY`.
- [ ] `tests/conftest.py` `clean_env` fixture scrubs `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and `GOOGLE_API_KEY` (in addition to existing vars). Without this, a developer's real API keys leak into test runs via Pydantic `BaseSettings` auto-parsing.
- [ ] `VERSION` bumped to `1.0.0` on develop before merge to main.
