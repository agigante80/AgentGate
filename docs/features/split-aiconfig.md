# Split AIConfig into Backend-Specific Sub-Configs

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-13

Refactor the flat `AIConfig` class into a top-level config plus three backend-specific
sub-configs (`CopilotAIConfig`, `CodexAIConfig`, `DirectAIConfig`), while keeping all
existing env var names unchanged for zero-downtime migration.

---

## ⚠️ Prerequisite Questions

1. **Scope** — `src/config.py`, `src/ai/factory.py`, `src/ready_msg.py`, and tests that mock `AIConfig`.
2. **Backward compatibility** — All existing env var names (`COPILOT_SKILLS_DIRS`, `AI_API_KEY`, `AI_MODEL`, `AI_PROVIDER`, `AI_BASE_URL`, `SYSTEM_PROMPT_FILE`, `AI_CLI_OPTS`) remain unchanged. Two new optional env vars are added (`CODEX_API_KEY`, `CODEX_MODEL`) for per-backend overrides.
3. **Breaking change?** — No runtime env-var change. Internal Python API changes (field paths change), but only internal callsites need updating. MINOR version bump.
4. **New dependency?** — None. Pydantic `BaseSettings` already handles nested models.
5. **Subprocess env isolation** — The primary correctness goal: each backend subprocess only receives the env vars it needs, not the secrets of sibling backends.
6. **Bot/Slack symmetry** — Both platforms share the same `AIConfig`; this refactor is platform-agnostic.
7. **VoiceConfig interaction** — `VoiceConfig.whisper_api_key` already falls back to `AIConfig.ai_api_key` in `src/transcriber.py`. This field stays at the top `AIConfig` level; no change needed.

---

## Problem Statement

1. **Mixed concerns** — `AIConfig` holds `copilot_skills_dirs` (Copilot-only), `ai_provider`/`ai_base_url`/`system_prompt_file` (api-only), and `ai_api_key`/`ai_model` (shared). There is no type-level boundary between them.
2. **Subprocess env leakage** — `CodexBackend._make_cmd()` injects `OPENAI_API_KEY` from `AIConfig.ai_api_key`. `CopilotBackend.__init__()` may set `COPILOT_SKILLS_DIRS`. Nothing in the type system prevents a future contributor from accidentally passing Codex secrets to Copilot subprocesses or vice-versa.
3. **Growing flat namespace** — Each new backend currently pollutes the shared `AIConfig` namespace. `CodexConfig` has no per-backend overrides (model, API key) because there is nowhere clean to put them. Adding `CODEX_MODEL` today would be ad-hoc.
4. **Discoverability** — Users examining `AIConfig` see all eight fields with no indication of which apply to their chosen backend. Sub-configs make the relationship obvious.

Affected: developers adding new AI backends; operators setting env vars who must read the source to understand which vars apply to their `AI_CLI` setting.

---

## Current Behaviour (as of v0.12.0)

| Field | Env Var | Used by | Location |
|-------|---------|---------|----------|
| `ai_cli` | `AI_CLI` | factory dispatch | `AIConfig` |
| `ai_cli_opts` | `AI_CLI_OPTS` | copilot + codex subprocess | `AIConfig` |
| `copilot_skills_dirs` | `COPILOT_SKILLS_DIRS` | copilot only | `AIConfig` |
| `system_prompt_file` | `SYSTEM_PROMPT_FILE` | api only | `AIConfig` |
| `ai_provider` | `AI_PROVIDER` | api only | `AIConfig` |
| `ai_api_key` | `AI_API_KEY` | codex + api + voice fallback | `AIConfig` |
| `ai_model` | `AI_MODEL` | copilot + codex + api + ready_msg | `AIConfig` |
| `ai_base_url` | `AI_BASE_URL` | api only | `AIConfig` |

> **Key gap**: no type boundary prevents `CopilotBackend` from accidentally accessing `ai_provider`, and `CodexBackend` has no way to accept a backend-specific key without sharing the generic `AI_API_KEY` with the api backend.

---

## Design Space

### Axis 1 — Sub-config as `BaseSettings` vs plain `BaseModel`

#### Option A — Nested `BaseSettings` *(recommended)*

Each sub-config is itself a `BaseSettings` instance. Python/Pydantic reads its env vars independently, and the parent `AIConfig` stores a reference.

```python
class CopilotAIConfig(BaseSettings):
    copilot_skills_dirs: str = ""  # reads COPILOT_SKILLS_DIRS

class AIConfig(BaseSettings):
    copilot: CopilotAIConfig = Field(default_factory=CopilotAIConfig)
```

**Pros:** Same env-var reading semantics as today; no custom validators needed.
**Cons:** Each nested `BaseSettings` reads from env independently — fine for our use case.

#### Option B — Plain `BaseModel` with custom env loading

Sub-configs are `BaseModel`; the parent `AIConfig` populates them from its own env-var read.

**Pros:** Single pass over env vars.
**Cons:** Requires custom `model_validator`; more complex; diverges from established pattern in this codebase.

**Recommendation: Option A** — consistent with how `Settings` already nests sub-configs.

---

### Axis 2 — Which fields stay at `AIConfig` top level

#### Option A — All shared fields at top level *(recommended)*

`ai_cli`, `ai_cli_opts`, `ai_api_key`, `ai_model` remain on `AIConfig` because they are either truly shared (fallback key/model for codex, voice, redactor) or read by non-factory code (`ready_msg.py`, `src/redact.py`).

Only fields that are *exclusively* used by one backend migrate to sub-configs.

**Pros:** Minimises callsite changes; `settings.ai.ai_api_key` still works in `redact.py`; no need to update `ready_msg.py` for model/key.
**Cons:** `AIConfig` still has a few multi-use fields.

#### Option B — Move everything to sub-configs

`ai_api_key` and `ai_model` move to `DirectAIConfig`; other callers (redactor, ready_msg) must go via `settings.ai.direct.*`.

**Pros:** Cleanest separation.
**Cons:** Cascades changes to 5+ non-factory files; wider diff; higher risk.

**Recommendation: Option A** — keep `ai_api_key`, `ai_model` shared at top level. Only migrate exclusively-backend fields.

---

## Recommended Solution

- **Axis 1**: Option A — nested `BaseSettings` sub-configs.
- **Axis 2**: Option A — shared fallback fields stay at `AIConfig` top level.

### New structure

```python
class CopilotAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=copilot."""
    copilot_skills_dirs: str = ""     # COPILOT_SKILLS_DIRS (unchanged)

class CodexAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=codex. Fall back to AIConfig shared fields when empty."""
    codex_api_key: str = ""           # CODEX_API_KEY (NEW — falls back to ai.ai_api_key)
    codex_model: str = ""             # CODEX_MODEL (NEW — falls back to ai.ai_model)

class DirectAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=api (DirectAPIBackend)."""
    ai_provider: Literal["openai", "anthropic", "ollama", "openai-compat", ""] = ""
    ai_base_url: str = ""             # AI_BASE_URL (unchanged)
    system_prompt_file: str = ""      # SYSTEM_PROMPT_FILE (unchanged)

class AIConfig(BaseSettings):
    """Top-level AI configuration — shared fields + backend sub-configs."""
    ai_cli: Literal["copilot", "codex", "api"] = "copilot"
    ai_cli_opts: str = ""             # AI_CLI_OPTS (shared; each backend may use or ignore)
    ai_api_key: str = ""             # AI_API_KEY (shared fallback; also used by voice redactor)
    ai_model: str = ""               # AI_MODEL (shared fallback; also used by ready_msg)
    copilot: CopilotAIConfig = Field(default_factory=CopilotAIConfig)
    codex: CodexAIConfig = Field(default_factory=CodexAIConfig)
    direct: DirectAIConfig = Field(default_factory=DirectAIConfig)
```

### Factory access patterns (after)

| Backend | Field | Access path |
|---------|-------|-------------|
| Copilot | skills dirs | `ai.copilot.copilot_skills_dirs` |
| Copilot | model | `ai.ai_model` (shared) |
| Copilot | CLI opts | `ai.ai_cli_opts` (shared) |
| Codex | API key | `ai.codex.codex_api_key or ai.ai_api_key` |
| Codex | model | `ai.codex.codex_model or ai.ai_model or "o3"` |
| Codex | CLI opts | `ai.ai_cli_opts` (shared) |
| Direct | provider | `ai.direct.ai_provider` |
| Direct | API key | `ai.ai_api_key` (shared) |
| Direct | model | `ai.ai_model` (shared) |
| Direct | base URL | `ai.direct.ai_base_url` |
| Direct | system prompt file | `ai.direct.system_prompt_file` |

### `ready_msg.py` access (after)

```python
# ai_label() — minimal change: ai_provider moves to ai.direct
def ai_label(settings: Settings) -> str:
    cli = settings.ai.ai_cli
    model = settings.ai.ai_model          # unchanged (shared)
    provider = settings.ai.direct.ai_provider   # was settings.ai.ai_provider
    ...
```

---

## Architecture Notes

- `SecretRedactor` in `src/redact.py` reads `settings.ai.ai_api_key` — this field stays at the top level; no change required.
- `VoiceConfig` falls back to `ai.ai_api_key` in `src/transcriber.py`; unchanged.
- `CodexBackend._make_cmd()` sets `OPENAI_API_KEY` in subprocess env — after refactor it will use `ai.codex.codex_api_key or ai.ai_api_key`, ensuring the Codex subprocess only gets the key intended for it.
- `CopilotBackend.__init__()` sets `COPILOT_SKILLS_DIRS` and `COPILOT_MODEL` in the subprocess env from the `CopilotAIConfig` fields — no leakage of Codex/Direct secrets into Copilot subprocesses.
- Pydantic `BaseSettings` nested via `Field(default_factory=...)` instantiates each sub-config independently, so each reads from the same flat environment but only maps its own fields.

---

## Config Variables

### Existing (env var names unchanged)

| Env Var | Type | Default | Used by |
|---------|------|---------|---------|
| `AI_CLI` | `copilot\|codex\|api` | `copilot` | All |
| `AI_CLI_OPTS` | `str` | `""` | copilot, codex |
| `AI_API_KEY` | `str` | `""` | codex (fallback), api, voice |
| `AI_MODEL` | `str` | `""` | copilot, codex (fallback), api, ready_msg |
| `COPILOT_SKILLS_DIRS` | `str` | `""` | copilot only |
| `AI_PROVIDER` | `str` | `""` | api only |
| `AI_BASE_URL` | `str` | `""` | api only |
| `SYSTEM_PROMPT_FILE` | `str` | `""` | api only |

### New (additive — no migration required for existing deployments)

| Env Var | Type | Default | Purpose |
|---------|------|---------|---------|
| `CODEX_API_KEY` | `str` | `""` | Per-backend OpenAI key for Codex. Falls back to `AI_API_KEY` when empty. Allows Codex and Direct API to use different keys. |
| `CODEX_MODEL` | `str` | `""` | Per-backend model for Codex (e.g. `o3-mini`). Falls back to `AI_MODEL` when empty, then `o3`. |

---

## Implementation Steps

1. **`src/config.py`** — Add `CopilotAIConfig`, `CodexAIConfig`, `DirectAIConfig` before `AIConfig`. Remove `copilot_skills_dirs`, `ai_provider`, `ai_base_url`, `system_prompt_file` from flat `AIConfig`. Add nested fields `copilot`, `codex`, `direct`. Keep `ai_api_key`, `ai_model`, `ai_cli_opts` at top level.
2. **`src/ai/factory.py`** — Update all `ai.*` field accesses to use sub-config paths. Add fallback logic for `codex_api_key` / `codex_model`.
3. **`src/ready_msg.py`** — Update `ai_label()` to read `settings.ai.direct.ai_provider` instead of `settings.ai.ai_provider`.
4. **`tests/unit/test_ready_msg.py`** — Update mock setup to use `ai.direct.ai_provider` instead of `ai.ai_provider`.
5. **`tests/integration/test_startup.py`** — Update mock setup similarly.
6. **`tests/unit/test_bot_handlers.py`** — Remove/update mock fields that no longer exist on `AIConfig` spec.
7. **`tests/unit/test_config_split.py`** (new) — Unit tests for sub-config isolation and fallback logic (see Test Plan).
8. **`VERSION`** — Bump MINOR: `0.12.0` → `0.13.0`.

---

## Files to Create / Change

| File | Action | Description |
|------|--------|-------------|
| `src/config.py` | Change | Add 3 sub-config classes; update `AIConfig` |
| `src/ai/factory.py` | Change | Update field access paths; add codex fallback logic |
| `src/ready_msg.py` | Change | `ai.ai_provider` → `ai.direct.ai_provider` |
| `tests/unit/test_ready_msg.py` | Change | Update mock to set `ai.direct.ai_provider` |
| `tests/integration/test_startup.py` | Change | Update mock to set `ai.direct.ai_provider` |
| `tests/unit/test_bot_handlers.py` | Change | Remove `ai.ai_provider` from mock (unused) |
| `tests/unit/test_config_split.py` | Create | Isolation + fallback unit tests |
| `VERSION` | Change | `0.12.0` → `0.13.0` |

---

## Dependencies

| Package | Status |
|---------|--------|
| `pydantic-settings` | Already installed |

---

## Test Plan

### New tests in `tests/unit/test_config_split.py`

| Test | What it checks |
|------|---------------|
| `test_copilot_sub_config_reads_own_env` | `CopilotAIConfig` reads `COPILOT_SKILLS_DIRS` from env |
| `test_codex_sub_config_reads_own_env` | `CodexAIConfig` reads `CODEX_API_KEY` and `CODEX_MODEL` |
| `test_direct_sub_config_reads_own_env` | `DirectAIConfig` reads `AI_PROVIDER`, `AI_BASE_URL`, `SYSTEM_PROMPT_FILE` |
| `test_codex_api_key_fallback` | Factory uses `codex_api_key` when set; falls back to `ai_api_key` when empty |
| `test_codex_model_fallback` | Factory uses `codex_model` when set; falls back to `ai_model`, then `"o3"` |
| `test_copilot_env_has_no_openai_key` | `CopilotBackend` subprocess env does not contain `OPENAI_API_KEY` (unless system env has it) |
| `test_codex_env_has_no_copilot_dirs` | `CodexBackend` subprocess env does not set `COPILOT_SKILLS_DIRS` from config |
| `test_aiconfig_shared_fields_unchanged` | `ai_api_key`, `ai_model`, `ai_cli`, `ai_cli_opts` still on `AIConfig` |
| `test_factory_copilot_path` | `create_backend()` with copilot config creates `CopilotBackend` with correct args |
| `test_factory_codex_path` | `create_backend()` with codex config creates `CodexBackend` with correct resolved key/model |
| `test_factory_direct_path` | `create_backend()` with api config creates `DirectAPIBackend` with correct args |

---

## Documentation Updates

- [ ] `README.md` — Update env var reference table: add `CODEX_API_KEY`, `CODEX_MODEL`
- [ ] `docs/features/split-aiconfig.md` — Set status to `Implemented` after merge
- [ ] `docs/roadmap.md` — Remove item 1.4 after merge
- [ ] `VERSION` — Bump to `0.13.0`

---

## Edge Cases & Open Questions

1. **`CODEX_API_KEY` not set** — factory falls back to `ai.ai_api_key`. If that is also empty, Codex will fail at runtime (existing behaviour; no regression).
2. **`ai_provider` in `ready_msg.py`** — after moving to `direct.ai_provider`, `ai_label()` will show `copilot (o3)` instead of `api/openai (o3)` if someone accidentally sets `AI_CLI=copilot` with provider env vars set. This is correct — provider is irrelevant for copilot.
3. **MagicMock(spec=AIConfig) in tests** — `ai.ai_provider` is no longer in the spec. Tests that set `ai.ai_provider = ...` still work (MagicMock allows setting any attribute), but the set value won't be auto-validated. Update mocks to be explicit.
4. **`SYSTEM_PROMPT` (inline text)** — currently in `BotConfig.system_prompt`, not `AIConfig`. Not affected by this refactor.

---

## Acceptance Criteria

- [ ] `CopilotAIConfig`, `CodexAIConfig`, `DirectAIConfig` exist as distinct `BaseSettings` classes
- [ ] `AIConfig.copilot_skills_dirs` is removed; access via `ai.copilot.copilot_skills_dirs`
- [ ] `AIConfig.ai_provider`, `ai_base_url`, `system_prompt_file` removed; access via `ai.direct.*`
- [ ] `AIConfig.ai_api_key`, `ai_model`, `ai_cli`, `ai_cli_opts` remain at top level
- [ ] `CODEX_API_KEY` and `CODEX_MODEL` are new optional env vars for Codex overrides
- [ ] All existing env var names still work unchanged
- [ ] `factory.py` uses sub-config paths with correct fallback logic
- [ ] `ready_msg.py` reads `ai.direct.ai_provider`
- [ ] `src/redact.py` and `src/transcriber.py` unchanged (still use `ai.ai_api_key`)
- [ ] `ruff check src/` passes
- [ ] All existing tests pass
- [ ] New isolation tests in `test_config_split.py` all pass
- [ ] `VERSION` bumped to `0.13.0`
