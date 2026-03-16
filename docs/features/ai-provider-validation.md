# AI Provider Explicit Validation (`AI_PROVIDER`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-16

Require `AI_PROVIDER` to be non-empty when `AI_CLI=api`; raise clear `ValueError` at startup.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/ai-provider-validation.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — This is a core config validation; affects both Telegram and Slack platforms during startup.
2. **Backend** — This applies specifically when `AI_CLI=api`, which uses the `DirectAPIBackend`.
3. **Stateful vs stateless** — This is a startup-time validation; it does not directly interact with backend statefulness at runtime.
4. **Breaking change?** — Yes. Existing deployments with `AI_CLI=api` but an empty `AI_PROVIDER` will now fail at startup with a `ValueError`. This warrants a MINOR version bump (or MAJOR if combined with other breaking changes).
5. **New dependency?** — No. Uses existing Python built-ins and Pydantic validation.
6. **Persistence** — No. Purely in-memory validation at startup.
7. **Auth** — No new secret/token/credential. It validates existing `AI_PROVIDER` and `AI_CLI` environment variables.

---

## Problem Statement

1. **Silent API failures** — When `AI_CLI=api` is set but `AI_PROVIDER` is empty (e.g., `AI_PROVIDER=""`), the `DirectAPIBackend` initializes without a specified provider. This often leads to silent failures or confusing error messages downstream when the `DirectAPIBackend` attempts to make API calls without knowing which provider (OpenAI, Anthropic, etc.) to target.
2. **Poor user experience** — Users have to debug runtime errors to discover that a required configuration variable (`AI_PROVIDER`) was missing or misconfigured, rather than receiving a clear, immediate startup error.
3. **Inconsistent validation** — Other critical configuration combinations are validated at startup. This specific combination (empty `AI_PROVIDER` with `AI_CLI=api`) is a notable omission.

Affected users: All users deploying AgentGate with `AI_CLI=api`.

---

## Current Behaviour (as of v0.20.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Config  | `src/config.py` (`AIConfig`) | `ai_provider: str = ""` (default empty string) |
| Backend | `src/ai/factory.py` (`AIBackendFactory.from_settings`) | `DirectAPIBackend` is instantiated even if `settings.ai.ai_provider` is empty. |
| Runtime | `src/ai/direct.py` (`DirectAPIBackend.send`) | API calls fail if `self.ai_provider` (from `AI_PROVIDER`) is empty, often with a generic client error. |

> **Key gap**: There is no explicit validation at startup to ensure `AI_PROVIDER` is set when `AI_CLI=api`, leading to confusing runtime errors.

---

## Design Space

### Axis 1 — Where to perform the validation

#### Option A — `AIConfig` Pydantic `model_validator` *(recommended)*

Add a `model_validator` to `AIConfig` in `src/config.py` that checks the condition.

**Pros:**
- Pydantic handles validation at the earliest possible stage (when `AIConfig` is loaded).
- Consistent with other Pydantic-based validations.
- Explicitly associated with `AIConfig`.

**Cons:**
- Requires understanding of Pydantic validators.

**Recommendation: Option A** — leverages existing Pydantic infrastructure for clean, early validation.

---

#### Option B — `_validate_config()` in `src/main.py`

Add a check in the `_validate_config()` function in `src/main.py`.

**Pros:**
- Centralized startup validation logic.
- Easier to implement for simple checks.

**Cons:**
- Further clutters `_validate_config()` which is already growing.
- Not as tightly coupled to `AIConfig` as a Pydantic validator.

---

### Axis 2 — Error handling

#### Option A — Raise `ValueError` *(recommended)*

Raise a `ValueError` with a clear message explaining the issue. This will be caught by the startup error handling in `main.py` and displayed to the user.

**Pros:**
- Clear, immediate feedback to the user at startup.
- Standard Python exception for invalid argument value.

**Cons:**
- Requires user to fix configuration before the bot can start.

**Recommendation: Option A** — provides direct and actionable feedback.

---

## Recommended Solution

- **Axis 1**: Option A — Add a Pydantic `model_validator` to `AIConfig` in `src/config.py`.
- **Axis 2**: Option A — Raise a `ValueError` with a clear message.

End-to-end flow:

```
Startup:
  1. `Settings.load()` attempts to load configurations, including `AIConfig`.
  2. `AIConfig`'s `model_validator` is triggered.
  3. If `ai_cli == "api"` and `ai_provider` is empty:
     - `ValueError` is raised with a message like "AI_PROVIDER must be set when AI_CLI=api".
  4. `main.py` catches the `ValueError` and prints the error message, preventing bot startup.
```

---

## Architecture Notes

- **`is_stateful` flag** — Not directly affected. This is a configuration validation.
- **`REPO_DIR` and `DB_PATH`** — Not affected.
- **Platform symmetry** — Validation is platform-agnostic, applied once at startup.
- **Auth guard** — Not affected. This is pre-authentication config validation.
- **Settings loading** — The validation occurs within `Settings.load()` as part of the Pydantic model instantiation.
- **`asyncio_mode = auto`** — Not directly relevant; tests will be synchronous.

---

## Config Variables

No new environment variables are introduced. This feature validates existing ones.

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `AI_CLI` | `str` | `"copilot"` | The AI CLI to use (e.g., `copilot`, `codex`, `api`). |
| `AI_PROVIDER` | `str` | `""` | The AI provider to use when `AI_CLI=api` (e.g., `openai`, `anthropic`, `google`). |

---

## Implementation Steps

### Step 1 — `src/config.py`: add `model_validator` to `AIConfig`

```python
# In src/config.py, inside the AIConfig class:
from pydantic import model_validator # Add this import at the top of the file

class AIConfig(BaseSettings):
    # ... existing fields ...

    @model_validator(mode="after")
    def validate_provider_for_api_cli(self) -> "AIConfig":
        if self.ai_cli == "api" and not self.ai_provider:
            raise ValueError("AI_PROVIDER must be set when AI_CLI=api")
        return self
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `model_validator` to `AIConfig` for `AI_PROVIDER` validation. |
| `tests/unit/test_config.py` | **Edit** | Add tests for `AI_PROVIDER` validation. |
| `docs/features/ai-provider-validation.md` | **Edit** | Mark status as `Implemented` after merge. |
| `docs/roadmap.md` | **Edit** | Mark item `2.18` as done (✅) after merge. |

---

## Dependencies

No new dependencies.

---

## Test Plan

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_ai_provider_required_for_api_cli` | `AI_CLI=api` with empty `AI_PROVIDER` raises `ValueError`. |
| `test_ai_provider_not_required_for_other_cli` | `AI_CLI=copilot` (or `codex`) with empty `AI_PROVIDER` does NOT raise `ValueError`. |
| `test_ai_provider_valid_for_api_cli` | `AI_CLI=api` with non-empty `AI_PROVIDER` passes validation. |

---

## Documentation Updates

### `README.md`

Update the `AI_CLI` and `AI_PROVIDER` descriptions in the Environment Variables table to reflect the new validation rule.

```markdown
| `AI_CLI`      | `copilot` | The AI CLI to use: `copilot`, `codex`, or `api`.                                            |
| `AI_PROVIDER` | `""`      | Required when `AI_CLI=api`. The AI provider to use (e.g., `openai`, `anthropic`, `google`). |
```

### `.env.example` and `docker-compose.yml.example`

Update the commented entries for `AI_CLI` and `AI_PROVIDER` to reflect the new validation.

```bash
# Required when AI_CLI=api. The AI provider to use (e.g., openai, anthropic, google).
# AI_PROVIDER=""
```

### `.github/copilot-instructions.md`

No changes needed.

### `docs/roadmap.md`

Mark item `2.18` as done (✅) once merged to `main`.

### `docs/features/ai-provider-validation.md`

Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`. Add `Implemented in: vX.Y.Z` (update with actual version).

---

## Version Bump

This introduces a breaking change for existing deployments that use `AI_CLI=api` with an unset `AI_PROVIDER`.

**Expected bump for this feature**: `MINOR` → `0.Y+1.0` (from current `0.20.x`).

---

## Roadmap Update

When this feature is complete, update `docs/roadmap.md`:

```markdown
| 2.18 | ✅ `AI_PROVIDER` explicit validation — require `AI_PROVIDER` when `AI_CLI=api` | [→ features/ai-provider-validation.md](features/ai-provider-validation.md) |
```

---

## Edge Cases and Open Questions

1. **User confusion with `AI_CLI=api` and no `AI_PROVIDER`**: The `ValueError` should provide sufficiently clear guidance.
2. **Impact on `build_app` and `_startup`**: The `ValueError` will be caught during `Settings.load()` in `main.py`, leading to an early exit, as desired.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] When `AI_CLI=api` and `AI_PROVIDER` is empty, the bot fails to start with a `ValueError` containing a clear message.
- [ ] When `AI_CLI=api` and `AI_PROVIDER` is set, the bot starts successfully.
- [ ] When `AI_CLI` is *not* `api` (e.g., `copilot`, `codex`), an empty `AI_PROVIDER` does *not* prevent startup.
- [ ] `README.md` is updated (env var table).
- [ ] `.env.example` and `docker-compose.yml.example` are updated to reflect the new validation.
- [ ] `docs/roadmap.md` entry `2.18` is marked done (✅).
- [ ] `docs/features/ai-provider-validation.md` status changed to `Implemented`.
- [ ] `VERSION` file bumped according to versioning guide (MINOR bump).
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
