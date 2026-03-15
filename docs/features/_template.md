# [Feature Name] (`gate <command>` or `ENV_VAR`)

> Status: **Planned** | Priority: High / Medium / Low | Last reviewed: YYYY-MM-DD

One-sentence summary of what this feature does and why it exists.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/<this-file>.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

> Answer these before writing a single line of code. A wrong assumption at the start
> costs 10× more to fix than a clarification takes.

1. **Scope** — Is this Telegram-only, Slack-only, or both platforms?
2. **Backend** — Does this apply to all AI backends (`copilot`, `codex`, `api`) or only some?
3. **Stateful vs stateless** — Does this interact differently with stateful backends
   (`CodexBackend.is_stateful = True`) vs. stateless ones (`CopilotBackend`, `DirectAPIBackend`)?
4. **Breaking change?** — Does this rename, remove, or change the behaviour of an existing
   env var, command, or Docker volume layout? → determines MAJOR vs MINOR version bump.
5. **New dependency?** — If a new pip/npm package is required, is it already present as a
   transitive dep (check `pip show <pkg>` in the container) or is an explicit pin needed?
6. **Persistence** — Does this need a new DB table, a new file in `/data/`, or no storage?
7. **Auth** — Does this require a new secret/token/credential? Where does it go in `config.py`?
8. **[Feature-specific question]** — Add any question whose answer would change the design.

---

## Problem Statement

Describe the user pain points in numbered form:

1. **[Pain point 1]** — What breaks, what is missing, or what is confusing today.
2. **[Pain point 2]** — …
3. **[Pain point 3]** — …

Include who is affected (Telegram users, Slack admins, self-hosters, etc.) and under what
conditions the problem occurs.

---

## Current Behaviour (as of v`X.Y.x`)

Map every relevant code location to what it does today. Use exact file paths and line numbers.

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| `[Layer name]` | `src/file.py:NN` (`function_name`) | What it does now |
| `[Layer name]` | `src/other.py:NN` | What it does now |
| Config | `src/config.py` (`SubConfig`) | Field name, type, and current default |
| `[Layer name]` | `src/platform/slack.py:NN` | Slack-specific behaviour |

> **Key gap**: Summarise in one or two sentences the architectural gap or missing behaviour
> that motivates this feature.

---

## Design Space

For each significant decision, list the options and their trade-offs before committing.
Use sub-headings per "axis" (decision dimension).

### Axis 1 — [Decision topic, e.g., "How to surface feedback to the user"]

#### Option A — [Name] *(status quo / baseline)*

Short description of the option.

```python
# Code sketch (if helpful)
```

**Pros:**
- …
- …

**Cons:**
- …
- …

---

#### Option B — [Name] *(recommended)*

Short description.

```python
# Code sketch
```

**Pros:**
- …

**Cons:**
- …

**Recommendation: Option B** — one sentence justification.

---

#### Option C — [Name]

…

---

### Axis 2 — [Next decision topic]

*(Repeat format above)*

---

## Recommended Solution

State the chosen options clearly:

- **Axis 1**: Option B — [one-line reason]
- **Axis 2**: Option X — [one-line reason]

Then describe the end-to-end design at a level a developer can follow:

```
[High-level flow or pseudo-code showing how the feature works at runtime]
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = True`.
  History injection in `platform/common.py:build_prompt()` only runs for stateless backends.
  This feature must respect that boundary.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode `/repo` or
  `/data/history.db`.
- **Platform symmetry** — every feature that changes `_run_ai_pipeline` or `_stream_to_*` in
  `src/bot.py` must have a mirrored change in `src/platform/slack.py`.
- **Auth guard** — all Telegram handlers must be decorated with `@_requires_auth`.
- **Settings loading** — `Settings.load()` is the only entry point; never instantiate sub-configs
  directly. Validation failures should raise `ValueError` to be caught in `_validate_config()`.
- **`asyncio_mode = auto`** — all `async def test_*` functions in `tests/` run without
  `@pytest.mark.asyncio`.
- **[Feature-specific note]** — Add any additional architectural constraint specific to this feature.

---

## Config Variables

List every new env var introduced. Follow the pattern of existing `BotConfig` / `AIConfig` fields.

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `NEW_VAR_ONE` | `bool` | `True` | Enable/disable feature (opt-out by default). |
| `NEW_VAR_TWO` | `int` | `30` | [What it controls]. Range: 1–3600. |
| `NEW_VAR_THREE` | `str` | `""` | [What it controls]. Empty string = disabled. |

> **Naming convention**: use `SCREAMING_SNAKE_CASE`. Group related vars with a common prefix
> (e.g., `SCHEDULE_*`, `THINKING_*`). Boolean flags default to the safer/conservative value.

---

## Implementation Steps

Ordered, file-by-file. Each step is self-contained and testable before moving to the next.

### Step 1 — `src/config.py`: add config fields

Add fields to the appropriate sub-config class. Follow the existing pattern:

```python
# In BotConfig (or AIConfig / VoiceConfig — pick the right one):
new_var_one: bool = Field(True, env="NEW_VAR_ONE")
new_var_two: int  = Field(30,   env="NEW_VAR_TWO")
new_var_three: str = Field("",  env="NEW_VAR_THREE")
```

If a new constant (like a DB path) is needed, add it at module level:

```python
NEW_DB_PATH: Final[str] = "/data/new_feature.db"
```

---

### Step 2 — `src/[new_module].py` (create, if needed)

Create `src/new_module.py`. Follow the pattern of `src/executor.py` or `src/history.py`:

```python
"""[Module docstring: one sentence on purpose.]"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


class NewClass:
    """[Class docstring.]"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def some_method(self, arg: str) -> str:
        """[Method docstring.]"""
        ...
```

---

### Step 3 — `src/[existing_module].py`: add logic

Describe what to add, where exactly, and why:

```python
# Add after line NN (after the `_requires_auth` guard):
async def cmd_new_feature(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gate new_feature command."""
    ...
```

---

### Step 4 — `src/bot.py`: wire up Telegram handler

Register the new command in `__init__` and the command dispatch table:

```python
# In _BotHandlers.__init__, add:
app.add_handler(CommandHandler("gate", self.cmd_new_feature))

# In the prefix dispatch dict:
"new_feature": self.cmd_new_feature,
```

---

### Step 5 — `src/platform/slack.py`: mirror for Slack

Mirror every change from Step 3–4 for the Slack bot. Keep logic DRY by calling the same
helper used in `bot.py`:

```python
# In SlackBot, add:
async def _handle_new_feature(self, body: dict, say: Say, client: AsyncWebClient) -> None:
    result = await shared_helper(self._settings, ...)
    await say(result)
```

---

### Step 6 — `src/main.py`: initialise on startup

If a new component needs setup (e.g., DB migration, background task), add it to
`main()` after the existing init sequence:

```python
# After `history.init_db()`:
await new_module.init(settings)
logger.info("New feature initialised.")
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `N` new fields to `[SubConfig]` |
| `src/new_module.py` | **Create** | `NewClass`, helper functions |
| `src/bot.py` | **Edit** | Add `cmd_new_feature`, wire handler |
| `src/platform/slack.py` | **Edit** | Mirror `cmd_new_feature` for Slack |
| `src/main.py` | **Edit** | Initialise `new_module` on startup |
| `README.md` | **Edit** | Feature bullet, env var rows, command table |
| `docs/features/[this-file].md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Mark item as done; add next-iteration item if any |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `some-package` | ✅ Already installed | Transitive via `python-telegram-bot`. Do NOT re-pin. |
| `new-package>=1.2` | ❌ Needs adding | Add to `requirements.txt`. Pin to minimum working version. |
| `dev-only-package` | ❌ Needs adding | Add to `requirements-dev.txt` only. |

> **Rule**: do not add explicit version pins for packages that are already transitive
> dependencies — it causes version-conflict headaches. Only pin direct dependencies.

---

## Test Plan

### `tests/unit/test_[feature].py` (new file)

| Test | What it checks |
|------|----------------|
| `test_[happy_path]` | Normal usage returns expected result |
| `test_[edge_case_1]` | [Edge condition] is handled gracefully |
| `test_[edge_case_2]` | [Edge condition] returns correct error/message |
| `test_[config_disabled]` | Feature is a no-op when disabled via env var |
| `test_[config_validation]` | Invalid config value raises `ValueError` |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_cmd_[feature]_happy` | Command dispatches correctly, response is sent |
| `test_cmd_[feature]_auth` | Unauthenticated user gets rejected |
| `test_cmd_[feature]_disabled` | Disabled feature returns informative message |

### `tests/contract/test_backends.py` additions *(if AI backend is affected)*

| Test | What it checks |
|------|----------------|
| `test_[feature]_all_backends` | All backends satisfy the updated `AICLIBackend` contract |

### `tests/integration/test_[feature]_integration.py` *(if DB or subprocess involved)*

| Test | What it checks |
|------|----------------|
| `test_[feature]_persists` | Data written to DB survives a re-initialisation |
| `test_[feature]_concurrent` | Concurrent calls do not corrupt state |

### Coverage note

Run `pytest tests/ --cov=src --cov-report=term-missing` after implementation. Target:
no uncovered branches in the new module. Any branch deliberately excluded must have
a `# pragma: no cover` comment with a one-line explanation.

---

## Documentation Updates

### `README.md`

Add entries in the relevant sections:

1. **Features bullet list** — one-line description with emoji.
2. **Environment variables table** — one row per new env var (both Telegram and Slack sections if applicable).
3. **Bot commands table** — one row per new `gate <cmd>`.

Example env var row:
```markdown
| `NEW_VAR_ONE` | `true` | Enable [feature name]. Set `false` to disable. |
```

### `.env.example` and `docker-compose.yml.example`

For every new env var introduced by this feature:

- [ ] Add a commented entry to `.env.example` with a sensible example value and a one-line description.
- [ ] Add a matching commented entry to `docker-compose.yml.example` under the appropriate platform block.
- [ ] Verify existing vars that this feature changes (renamed, removed, or new defaults) are updated in both files.

Example `.env.example` entry:
```bash
# Enable [feature name]. Set to false to disable. (default: true)
# NEW_VAR_ONE=true
```

Example `docker-compose.yml.example` entry:
```yaml
# NEW_VAR_ONE=true   # Enable [feature name]
```

### `.github/copilot-instructions.md`

If the feature introduces a new module, new architectural pattern, or new convention,
add a bullet to the relevant section. Keep it to one or two sentences — it is a
quick-reference file, not documentation.

### `docs/roadmap.md`

- Change the roadmap entry for this feature to include a ✅ once merged to `main`.
- If the feature has a follow-up iteration (v2, stretch goal), add it as a new row.

### `docs/features/[this-file].md`

- Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.
- Add `Implemented in: vX.Y.Z` below the status line.

---

## Version Bump

Consult `docs/versioning.md` for the full decision guide. Quick reference:

| This feature… | Bump |
|---------------|------|
| Adds new env vars with safe defaults, new commands, new backends | **MINOR** (`0.7.x` → `0.8.0`) |
| Fixes a bug with no user-visible API change | **PATCH** (`0.7.3` → `0.7.4`) |
| Renames/removes an existing env var or command | **MAJOR** (`0.7.x` → `1.0.0`) |

> **Rule**: bump `VERSION` on `develop` _before_ the merge PR to `main`. Never edit
> `VERSION` directly on `main`.

**Expected bump for this feature**: `MINOR` → `0.Y+1.0` *(update this line with the real bump)*

---

## Roadmap Update

When this feature is complete, update `docs/roadmap.md`:

```markdown
| 2.X | ✅ [Feature name] — [one-line summary] | [→ features/this-file.md](features/this-file.md) |
```

If a stretch goal or follow-up iteration was identified during implementation, add it:

```markdown
| 2.X+1 | [Follow-up feature] | [→ features/followup.md](features/followup.md) |
```

---

## Edge Cases and Open Questions

> Number these. Resolve each before (or during) implementation. If the answer changes
> the design, update the relevant section above.

1. **[Question 1]** — Describe the ambiguity. Proposed answer: [your best guess]. Needs
   confirmation from: [who / what].

2. **[Question 2]** — What happens when [edge condition]? E.g., what if the user runs
   `gate clear` while this feature is mid-operation?

3. **[Question 3]** — Is there a race condition between [component A] and [component B]?
   How should it be handled?

4. **`gate restart` interaction** — If this feature holds live state (open file handle, DB
   connection, background task), does `gate restart` clean it up correctly?

5. **Slack thread scope** — If this feature posts messages, does it respect existing Slack
   thread context or always post to the channel root?

6. **[Platform-specific question]** — Any Telegram-only or Slack-only consideration?

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` is updated (features bullet, env var table, commands table — both Telegram and Slack sections).
- [ ] `.env.example` updated with commented entries for all new env vars.
- [ ] `docker-compose.yml.example` updated with commented entries for all new env vars.
- [ ] `docs/roadmap.md` entry is marked done (✅).
- [ ] `docs/features/[this-file].md` status changed to `Implemented`.
- [ ] `.github/copilot-instructions.md` updated if a new module/pattern was added.
- [ ] `VERSION` file bumped according to versioning guide.
- [ ] All new env vars have a safe default that preserves existing behaviour for users
      who do not set them (opt-in, not opt-out, for potentially disruptive changes).
- [ ] Feature works on both **Telegram** and **Slack** (unless explicitly scoped to one).
- [ ] Feature works with **all AI backends** (`copilot`, `codex`, `api`) or documents
      explicitly which backends are supported and why others are excluded.
- [ ] Edge cases in the section above are resolved and either handled or documented.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
