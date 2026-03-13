# Input Sanitization & Auth Hardening

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-13

Eliminate shell injection in the `gate diff` command and harden auth guards so that empty/missing channel-ID configuration cannot silently bypass access control.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram and Slack). The same vulnerable pattern exists in `src/bot.py` and `src/platform/slack.py`.
2. **Backend** — All AI backends. The shell injection is in `executor.run_shell()`, which is backend-agnostic.
3. **Stateful vs stateless** — Not applicable; neither fix interacts with the stateful/stateless boundary.
4. **Breaking change?** — No. Tightening validation and sanitizing input do not change any public env var semantics. Users who supply valid git refs and correct channel IDs will see no behaviour change.
5. **New dependency?** — No. `shlex` and `re` are stdlib modules.
6. **Persistence** — No storage changes.
7. **Auth** — No new credentials. Existing `TG_CHAT_ID` / `SLACK_CHANNEL_ID` behaviour is tightened (empty values now cause a startup failure instead of a silent bypass).
8. **Backwards compatibility** — Deployments that currently rely on `TG_CHAT_ID=""` (unintentionally open to any chat) will break on startup with a clear error. This is the desired outcome — the previous behaviour was a security hole, not a feature.

---

## Problem Statement

1. **Shell injection via `gate diff`** — When a user provides a non-numeric argument to `gate diff` (e.g. `gate diff main; rm -rf /`), the value is interpolated unsanitized into a shell command passed to `asyncio.create_subprocess_shell()`. Any authenticated user can execute arbitrary commands on the host. This is a *remote code execution (RCE)* vulnerability.

2. **Auth bypass with empty channel ID** — `TG_CHAT_ID` defaults to `""`. The Telegram auth guard (`_is_allowed` in `bot.py`) compares `str(update.effective_chat.id) != settings.telegram.chat_id`. When `chat_id` is `""`, no real chat ID will ever match `""`, so the check *does* correctly reject — but `_validate_config()` only enforces this for the `telegram` platform. If a future refactor weakens the check, the empty default becomes exploitable. The Slack guard in `is_allowed_slack()` (`common.py:65-72`) skips the channel check entirely when `slack_channel_id` is `""`, and skips the user check when `allowed_users` is empty — meaning any user in any channel can use the bot.

Affected users: every self-hosted deployment. The shell injection requires an authenticated user; the Slack auth bypass means *unauthenticated* users may reach the bot.

---

## Current Behaviour (as of v0.9.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Telegram auth | `src/bot.py:31-38` (`_is_allowed`) | Compares `chat_id` to `settings.telegram.chat_id`; skips user check when `allowed_users` is empty |
| Slack auth | `src/platform/common.py:65-72` (`is_allowed_slack`) | Skips channel check when `slack_channel_id` is `""`; skips user check when `allowed_users` is empty |
| Telegram diff | `src/bot.py:259-274` (`cmd_diff`) | Interpolates unsanitized `arg` into `f"git diff {ref} ..."` passed to `executor.run_shell()` |
| Slack diff | `src/platform/slack.py:405-419` (`_cmd_diff`) | Same unsanitized interpolation as Telegram |
| Shell executor | `src/executor.py:36-38` (`run_shell`) | Uses `asyncio.create_subprocess_shell()` — executes the string through `/bin/sh` |
| Config defaults | `src/config.py:10` (`TelegramConfig.chat_id`) | Defaults to `""` |
| Config defaults | `src/config.py:19` (`SlackConfig.slack_channel_id`) | Defaults to `""` |
| Startup validation | `src/main.py:42-53` (`_validate_config`) | Requires `TG_CHAT_ID` for Telegram, but does not require `SLACK_CHANNEL_ID` for Slack |

> **Key gap**: User-controlled input flows into a shell command without sanitization, and the auth layer has a permissive default that can leave Slack deployments open to any workspace member.

---

## Design Space

### Axis 1 — How to sanitize the `gate diff` argument

#### Option A — `shlex.quote()` only

Wrap the user-supplied ref in `shlex.quote()` before interpolation:

```python
import shlex
safe_ref = shlex.quote(arg)
```

**Pros:**
- One-line fix, battle-tested stdlib function.

**Cons:**
- `shlex.quote()` wraps in single quotes — may produce unexpected git behaviour for valid refs containing unusual characters (rare but possible).
- Does not reject obviously invalid input; just escapes it.

---

#### Option B — Strict regex allowlist + `shlex.quote()` *(recommended)*

Validate the argument against a strict regex (`^[a-zA-Z0-9._\-/]+$`) that matches valid git ref characters. Reject anything else with a user-friendly error. Apply `shlex.quote()` as a defence-in-depth layer even for valid refs.

```python
import re, shlex

_SAFE_GIT_REF = re.compile(r"^[a-zA-Z0-9._\-/]+$")

def _sanitize_git_ref(ref: str) -> str | None:
    """Return the ref if safe, or None if it contains illegal characters."""
    return ref if _SAFE_GIT_REF.match(ref) else None
```

**Pros:**
- Blocks injection at the input validation layer — clearer error for the user.
- Defence-in-depth: `shlex.quote()` still applied even after validation.
- Regex covers all valid git branch/tag/SHA characters.

**Cons:**
- Slightly more code than Option A.

**Recommendation: Option B** — validate first, quote as a safety net.

---

#### Option C — Use `subprocess_exec` instead of `subprocess_shell`

Refactor `executor.run_shell()` to use `create_subprocess_exec()` with argument lists.

**Pros:**
- Eliminates shell injection system-wide.

**Cons:**
- Large blast radius — every caller of `run_shell()` needs refactoring.
- Some commands rely on shell features (`&&`, pipes, `||`). This is a significant architectural change.
- Out of scope for a targeted security fix; better suited as a separate roadmap item.

---

### Axis 2 — How to harden empty-config auth bypass

#### Option A — Fail at startup if channel ID is empty *(recommended)*

Add a check in `_validate_config()` that requires `SLACK_CHANNEL_ID` when `PLATFORM=slack`. Keep `TG_CHAT_ID` requirement as-is (already enforced).

```python
if settings.platform == "slack":
    if not settings.slack.slack_channel_id:
        raise ValueError("SLACK_CHANNEL_ID is required when PLATFORM=slack")
```

**Pros:**
- Fail-fast — operator sees the error on deploy, not at runtime.
- Consistent with Telegram behaviour (already requires `TG_CHAT_ID`).

**Cons:**
- Operators who intentionally left `SLACK_CHANNEL_ID` empty (trusting workspace-level access) will need to set it.

---

#### Option B — Runtime warning + permissive default

Log a warning when `slack_channel_id` is empty but don't block startup.

**Cons:**
- Warnings are often ignored. The security hole remains open.

**Recommendation: Option A** — fail at startup; security must be explicit.

---

## Recommended Solution

- **Axis 1**: Option B — strict regex allowlist + `shlex.quote()` defence-in-depth for `gate diff`.
- **Axis 2**: Option A — require `SLACK_CHANNEL_ID` at startup when `PLATFORM=slack`.

End-to-end flow for `gate diff`:

```
User sends: gate diff some-branch
    → arg = "some-branch"
    → _sanitize_git_ref("some-branch") → "some-branch" (passes regex)
    → ref = shlex.quote("some-branch") + " HEAD"
    → executor.run_shell(f"git diff {ref} --stat …")

User sends: gate diff main; rm -rf /
    → arg = "main; rm -rf /"
    → _sanitize_git_ref("main; rm -rf /") → None (fails regex)
    → bot replies: "❌ Invalid git ref. Use a branch name, tag, or SHA."
    → command is NOT executed.
```

---

## Architecture Notes

- **`is_stateful` flag** — Not relevant to this feature.
- **`REPO_DIR` and `DB_PATH`** — No changes to path handling.
- **Platform symmetry** — The `gate diff` fix must be applied in both `src/bot.py` and `src/platform/slack.py`.
- **Auth guard** — All Telegram handlers remain decorated with `@_requires_auth`.
- **Settings loading** — `_validate_config()` is the single validation entry point; the new `SLACK_CHANNEL_ID` check is added there.
- **`executor.run_shell()`** — The fix is in the callers (`cmd_diff`), not in `run_shell()` itself. A broader refactor of `run_shell()` to use `subprocess_exec` is a separate effort (see Design Space, Option C).

---

## Config Variables

No new env vars introduced. Existing vars affected:

| Env var | Change | Impact |
|---------|--------|--------|
| `SLACK_CHANNEL_ID` | Now *required* when `PLATFORM=slack` | Deployments that omitted it will fail at startup with a clear error message |

---

## Implementation Steps

### Step 1 — `src/bot.py` + `src/platform/slack.py`: add `_sanitize_git_ref()` and apply to `cmd_diff`

Create a shared validation helper (can live in `src/executor.py` or inline in both files):

```python
import re
import shlex

_SAFE_GIT_REF = re.compile(r"^[a-zA-Z0-9._\-/]+$")


def sanitize_git_ref(ref: str) -> str | None:
    """Return the ref shell-quoted if it's a valid git ref, or None otherwise."""
    if not _SAFE_GIT_REF.match(ref):
        return None
    return shlex.quote(ref)
```

In `cmd_diff` (both platforms), replace:

```python
ref = f"{arg} HEAD"
```

with:

```python
safe = sanitize_git_ref(arg)
if safe is None:
    await _reply(update, "❌ Invalid git ref — use a branch name, tag, or commit SHA.")
    return
ref = f"{safe} HEAD"
```

---

### Step 2 — `src/main.py`: require `SLACK_CHANNEL_ID`

In `_validate_config()`, add after the existing Slack token checks:

```python
if not settings.slack.slack_channel_id:
    raise ValueError(
        "SLACK_CHANNEL_ID is required when PLATFORM=slack — "
        "set it to the channel where the bot should operate"
    )
```

---

### Step 3 — Tests

Add unit tests covering:

- Valid git ref passes sanitization.
- Invalid git refs (containing `;`, `|`, `&`, spaces, backticks) are rejected.
- `cmd_diff` with a malicious argument returns the error message and does *not* call `run_shell()`.
- `_validate_config()` raises `ValueError` when `SLACK_CHANNEL_ID` is empty and `PLATFORM=slack`.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/executor.py` | **Edit** | Add `sanitize_git_ref()` helper (shared by both platforms) |
| `src/bot.py` | **Edit** | Use `sanitize_git_ref()` in `cmd_diff`; reject invalid refs |
| `src/platform/slack.py` | **Edit** | Use `sanitize_git_ref()` in `_cmd_diff`; reject invalid refs |
| `src/main.py` | **Edit** | Require `SLACK_CHANNEL_ID` in `_validate_config()` |
| `tests/unit/test_executor.py` | **Edit** | Add tests for `sanitize_git_ref()` |
| `tests/unit/test_bot.py` | **Edit** | Add test for `cmd_diff` with malicious input |
| `tests/unit/test_main.py` | **Edit** | Add test for Slack missing `SLACK_CHANNEL_ID` |
| `docs/features/input-sanitization.md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Add item 1.5; mark done after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `re` | ✅ stdlib | Regular expressions for ref validation |
| `shlex` | ✅ stdlib | Shell quoting for defence-in-depth |

No new packages required.

---

## Test Plan

### `tests/unit/test_executor.py` additions

| Test | What it checks |
|------|----------------|
| `test_sanitize_git_ref_valid_branch` | `sanitize_git_ref("feature/foo")` returns quoted string |
| `test_sanitize_git_ref_valid_sha` | `sanitize_git_ref("abc123")` returns quoted string |
| `test_sanitize_git_ref_valid_tag` | `sanitize_git_ref("v1.0.0")` returns quoted string |
| `test_sanitize_git_ref_semicolon` | `sanitize_git_ref("main; rm -rf /")` returns `None` |
| `test_sanitize_git_ref_pipe` | `sanitize_git_ref("main | cat /etc/passwd")` returns `None` |
| `test_sanitize_git_ref_backtick` | `` sanitize_git_ref("main`whoami`") `` returns `None` |
| `test_sanitize_git_ref_ampersand` | `sanitize_git_ref("main && echo pwned")` returns `None` |
| `test_sanitize_git_ref_dollar` | `sanitize_git_ref("main$(id)")` returns `None` |
| `test_sanitize_git_ref_empty` | `sanitize_git_ref("")` returns `None` |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_cmd_diff_malicious_ref_rejected` | `cmd_diff` with `"; rm -rf /"` replies with error and never calls `run_shell()` |
| `test_cmd_diff_valid_ref_allowed` | `cmd_diff` with `"main"` calls `run_shell()` normally |

### `tests/unit/test_main.py` additions

| Test | What it checks |
|------|----------------|
| `test_validate_config_slack_missing_channel_id` | `ValueError` raised when `SLACK_CHANNEL_ID=""` and `PLATFORM=slack` |

---

## Documentation Updates

### `README.md`

No user-facing feature change. No update needed.

### `.github/copilot-instructions.md`

No new module or architectural pattern introduced.

### `docs/roadmap.md`

Add item 1.5 linking to this feature document.

### `docs/features/input-sanitization.md`

Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.

---

## Version Bump

This is a security fix with no user-visible API change (no new env vars, no new commands, no renamed configs).

**Expected bump**: `PATCH` → `0.9.1`

---

## Edge Cases and Open Questions

1. **Valid git refs with unusual characters** — Git allows refs like `feature/foo.bar-baz_v2`. The regex `^[a-zA-Z0-9._\-/]+$` covers all standard git ref characters. Refs with `~`, `^`, or `:` (used in refspecs like `HEAD~3`) are already handled by the `isdigit()` branch and never reach the regex path.

2. **`gate diff 3` (numeric arg)** — The `isdigit()` branch constructs `HEAD~3 HEAD`, which never contains user-controlled shell metacharacters. No sanitization needed for this path, but `shlex.quote()` can be applied for consistency.

3. **Existing deployments without `SLACK_CHANNEL_ID`** — These will fail at startup. This is intentional — the previous behaviour was a security vulnerability. The error message clearly states what to set.

4. **`gate restart` interaction** — No live state or background tasks involved; the fix is purely in request handling.

5. **Slack thread scope** — Not affected; the fix is in command parsing, not message posting.

6. **Other commands using `run_shell()`** — `cmd_log` uses a validated integer (`n`). The AI pipeline passes the full user prompt through the AI backend, not through a shell. No other commands interpolate user input into shell strings. A future audit should verify this remains true as new commands are added.

---

## Acceptance Criteria

- [ ] `sanitize_git_ref()` rejects all shell metacharacters (`;`, `|`, `&`, `` ` ``, `$`, `(`, `)`, spaces, newlines).
- [ ] `gate diff <malicious_input>` returns an error message without executing a shell command.
- [ ] Fix applied to both `src/bot.py` (Telegram) and `src/platform/slack.py` (Slack).
- [ ] `_validate_config()` raises `ValueError` when `PLATFORM=slack` and `SLACK_CHANNEL_ID` is empty.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `docs/roadmap.md` item 1.5 added with link to this document.
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
