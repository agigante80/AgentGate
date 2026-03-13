# Secret Redaction (`ALLOW_SECRETS`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-13

Prevent the AI from leaking environment secrets (tokens, API keys) in chat messages
and git commit messages, even if the AI is explicitly asked to reveal them.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both Telegram and Slack platforms.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). The AI subprocess has
   access to `os.environ` and can echo secret values in its output.
3. **Stateful vs stateless** — Applies equally. Redaction is on the *output* path,
   after the AI response is received but before it is posted to the user.
4. **Breaking change?** — No. Default behaviour changes from "show everything" to
   "redact secrets", but this is a security hardening with a safe default. MINOR bump.
5. **New dependency?** — None. Uses only stdlib `re` and string operations.
6. **Persistence** — No storage needed. Secrets are read from live config on startup.
7. **Auth** — No new credentials. Uses existing secret fields from config.

---

## Problem Statement

1. **AI leaks secrets in responses** — The AI backend subprocess inherits the full
   `os.environ` (see `src/ai/copilot.py:14`, `src/ai/codex.py:19`). When a user asks
   "compare branches" or "check CI status", the AI may construct shell commands that
   include tokens inline (e.g. `TOKEN="ghp_Ie5V…" curl -H "Authorization: …"`). The
   full command *and* output are posted to the chat channel.
2. **No opt-in gate for secret visibility** — There is currently no configuration to
   suppress secret output. Even private channels can be screenshotted, shared, or
   audited. The only protection is channel privacy, which is insufficient.
3. **Commit messages may contain secrets** — The AI can run `git commit -m "…"` inside
   the repo container. If the commit message includes a token or key (e.g. from the
   AI's working context), the secret is permanently recorded in git history.

Affected users: all deployers of AgentGate (both Telegram and Slack).

---

## Current Behaviour (as of v0.9.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| AI subprocess env | `src/ai/copilot.py:14` | `{**os.environ}` copies every env var (including secrets) to child process |
| AI subprocess env | `src/ai/codex.py:19` | Same — full env inherited |
| Telegram output | `src/bot.py:45-46` (`_reply`) | Posts text verbatim via `reply_text()` |
| Telegram output | `src/bot.py:87,110` (`_stream_to_telegram`) | Edits message with raw `accumulated` text during streaming |
| Telegram output | `src/bot.py:208` (`_run_ai_pipeline`) | Edits message with raw AI response |
| Slack output | `src/platform/slack.py:141-143` (`_send`) | Posts text verbatim via `say()` |
| Slack output | `src/platform/slack.py:145-150` (`_edit`) | Updates message with raw text via `chat_update()` |
| Slack output | `src/platform/slack.py:152-159` (`_reply`) | Posts text verbatim via `chat_postMessage()` |
| Slack streaming | `src/platform/slack.py:197` | Edits message with raw `accumulated` text |
| Shell execution | `src/executor.py:36-46` (`run_shell`) | Returns raw stdout (including any secrets printed by commands) |
| Shell summarization | `src/executor.py:49-53` (`summarize_if_long`) | Sends raw output to AI for summarization — secret could survive in summary |
| Config | `src/config.py` (`BotConfig`) | No `allow_secrets` or redaction field exists |

> **Key gap**: There is no redaction layer between the AI response and the chat output.
> Every message reaches the user exactly as the AI produced it.

---

## Design Space

### Axis 1 — Where to apply redaction

#### Option A — Redact only at final output (`_reply` / `_edit`)

Apply redaction in the Telegram `_reply()`, `_stream_to_telegram()` and the Slack
`_send()`, `_edit()`, `_reply()` methods.

**Pros:**
- Single choke point — impossible to bypass
- Catches everything: AI responses, shell output, error messages

**Cons:**
- Streaming chunks may show partial secrets before the next edit replaces them
  (mitigated by the throttle interval being 1s — partial display is brief)
- Does not prevent secrets from being written to git commit messages

#### Option B — Redact at output *and* in `run_shell()` for git commits *(recommended)*

Same as Option A, plus intercept `git commit` commands in `run_shell()` to redact the
commit message *before execution*.

**Pros:**
- Covers both output (what the user sees) and persistence (what stays in git history)
- Defence in depth

**Cons:**
- Slightly more complex (must parse git commit commands)

**Recommendation: Option B** — defence in depth: redact outgoing messages and also
prevent secrets from being written to git history.

---

### Axis 2 — How to detect secrets

#### Option A — Value-based only

Compare outgoing text against known secret values loaded from `Settings` at startup.
Replace any exact match with `[REDACTED]`.

**Pros:**
- Zero false positives — only redacts actual configured secrets

**Cons:**
- Misses secrets the AI generates on its own (e.g. if the AI invents a fake token)
- Does not catch secrets from env vars not modelled in `Settings`

#### Option B — Value-based + pattern-based *(recommended)*

Value-based matching (as above) *plus* regex patterns for common secret formats:
- GitHub PATs: `ghp_[A-Za-z0-9]{36}`, `gho_*`, `ghs_*`, `ghr_*`, `github_pat_*`
- Slack tokens: `xoxb-`, `xoxp-`, `xapp-`, `xoxs-`
- Generic: `Bearer [A-Za-z0-9\-._~+/]+=*` (Authorization headers)
- API keys: `sk-[A-Za-z0-9]{20,}` (OpenAI-style)
- URLs with embedded credentials: `https?://[^@\s]+:[^@\s]+@`

**Pros:**
- Catches secrets that aren't in our config (e.g. from env vars the AI reads directly)
- Catches secrets the AI constructs dynamically

**Cons:**
- Small false-positive risk (mitigated by well-scoped patterns)

**Recommendation: Option B** — value-based for known secrets, pattern-based for unknown ones.

---

### Axis 3 — Config variable semantics

#### Option A — `REDACT_SECRETS=true` (opt-out)

Default is to redact. Set `REDACT_SECRETS=false` to allow secrets.

#### Option B — `ALLOW_SECRETS=false` (opt-in to show secrets) *(recommended)*

Default is `false` (secrets are redacted). Set `ALLOW_SECRETS=true` to let secrets
pass through.

**Recommendation: Option B** — the variable name `ALLOW_SECRETS` is clearer about the
dangerous state. The safe default (`false`) means existing deployments are protected
after upgrade with no config change.

---

## Recommended Solution

- **Axis 1**: Option B — redact at output layer *and* in `run_shell()` for git commits
- **Axis 2**: Option B — value-based + pattern-based detection
- **Axis 3**: Option B — `ALLOW_SECRETS=false` (redact by default)

```
User → AI backend → raw response
                         ↓
                   redact(text, settings) ← value-based + pattern-based
                         ↓
                   _reply() / _edit() → user sees [REDACTED]

AI backend → run_shell("git commit -m '...'")
                         ↓
               if git commit detected:
                   redact commit message before execution
                         ↓
               execute sanitized command
```

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **`is_stateful` flag** — `CopilotBackend.is_stateful = False`; `CodexBackend.is_stateful = True`.
  Redaction is backend-agnostic — it operates on the output text regardless of backend.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`.
- **Platform symmetry** — redaction must be applied in *both* `src/bot.py` (Telegram) and
  `src/platform/slack.py` (Slack). Use a shared function from `src/redact.py`.
- **Streaming** — during streaming, each intermediate chunk posted via `_edit()` must also
  be redacted. A partial token at a chunk boundary could slip through for one edit cycle
  (≤1s at default throttle). This is acceptable — the final message is always fully redacted.
- **`summarize_if_long()`** — the raw text sent to the AI for summarization (`executor.py:52`)
  may still contain secrets. The AI sees them internally but the *summarized output* is
  redacted before reaching the user. This is acceptable because the AI subprocess already
  has full env access anyway.
- **Git commit interception** — `run_shell()` is the only path for shell commands in both
  Telegram and Slack handlers. The Copilot/Codex subprocess can also run git commits
  internally (via `--allow-all` / `--approval-mode full-auto`). To cover this, install a
  `commit-msg` git hook in `REPO_DIR` at startup that redacts secrets from commit messages.
  This catches commits from *any* source (bot commands, AI subprocess, manual).
- **`asyncio_mode = auto`** — all `async def test_*` functions run without `@pytest.mark.asyncio`.
- **Never redact `ALLOW_SECRETS` itself** — the variable name is not a secret, only secret values are.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `ALLOW_SECRETS` | `bool` | `False` | When `false` (default), secrets are redacted from all outgoing messages and git commit messages. Set `true` to allow secrets to pass through (dangerous — use only in trusted, private channels). |

> **Naming convention**: `ALLOW_SECRETS` clearly communicates the dangerous state.
> Boolean default is the safer value (`False` = redact).

---

## Implementation Steps

### Step 1 — `src/config.py`: add `allow_secrets` field

Add to `BotConfig`:

```python
allow_secrets: bool = False  # ALLOW_SECRETS: set true to permit secrets in output (default: redact)
```

---

### Step 2 — `src/redact.py` (create)

Create the redaction module with two layers:

```python
"""Redact secrets from outgoing text."""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"

# ── Pattern-based detection ──────────────────────────────────────────────────

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),                    # GitHub PAT (classic)
    re.compile(r"gho_[A-Za-z0-9]{36,}"),                    # GitHub OAuth token
    re.compile(r"ghs_[A-Za-z0-9]{36,}"),                    # GitHub server-to-server
    re.compile(r"ghr_[A-Za-z0-9]{36,}"),                    # GitHub refresh token
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),            # GitHub fine-grained PAT
    re.compile(r"xoxb-[A-Za-z0-9\-]{20,}"),                 # Slack bot token
    re.compile(r"xoxp-[A-Za-z0-9\-]{20,}"),                 # Slack user token
    re.compile(r"xapp-[A-Za-z0-9\-]{20,}"),                 # Slack app-level token
    re.compile(r"xoxs-[A-Za-z0-9\-]{20,}"),                 # Slack session token
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                     # OpenAI API key
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}=*"),     # Authorization header
    re.compile(r"https?://[^\s@]+:[^\s@]+@[^\s]+"),         # URL with embedded creds
]


class SecretRedactor:
    """Redact known secret values and common secret patterns from text."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = not settings.bot.allow_secrets
        self._known_values: list[str] = []
        if self._enabled:
            self._known_values = self._collect_secrets(settings)
            logger.info(
                "Secret redaction enabled (%d known values, %d patterns)",
                len(self._known_values), len(_SECRET_PATTERNS),
            )

    @staticmethod
    def _collect_secrets(settings: Settings) -> list[str]:
        """Gather non-empty secret values from all config sub-objects."""
        candidates = [
            settings.telegram.bot_token,
            settings.slack.slack_bot_token,
            settings.slack.slack_app_token,
            settings.github.github_repo_token,
            settings.ai.ai_api_key,
            settings.voice.whisper_api_key,
        ]
        # Only include values that are long enough to avoid false-positive matches
        return [v for v in candidates if v and len(v) >= 8]

    def redact(self, text: str) -> str:
        """Return text with secrets replaced by [REDACTED]."""
        if not self._enabled or not text:
            return text
        # Value-based: replace known secret values
        for secret in self._known_values:
            if secret in text:
                text = text.replace(secret, _REDACTED)
        # Pattern-based: replace common secret formats
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(_REDACTED, text)
        return text

    def redact_git_commit_cmd(self, cmd: str) -> str:
        """If cmd is a git commit, redact secrets from the message."""
        if not self._enabled:
            return cmd
        # Match common git commit invocations including `git -C <path> commit`
        if "git commit" not in cmd and "git -c" not in cmd and "git -C" not in cmd:
            return cmd
        return self.redact(cmd)
```

---

### Step 3 — `src/bot.py`: apply redaction to Telegram output

> **Architecture note**: `_reply()` in `bot.py` is a *module-level function* (`async def _reply(update, text)`), not a method on `_BotHandlers`. It has no access to `self` or the redactor. Apply redaction in each handler method *before* calling `_reply()` or `msg.edit_text()`, using `self._redactor.redact(text)`.

Concrete changes:

1. In `_BotHandlers.__init__`, create `self._redactor = SecretRedactor(settings)`.
2. In `_stream_to_telegram()` (`src/bot.py:49`), before each `msg.edit_text()` call, wrap the `display` variable: `display = self._redactor.redact(display)`.
3. In `_run_ai_pipeline()` (`src/bot.py:155`), before the final `msg.edit_text(response, …)` call, wrap: `response = self._redactor.redact(response)`.
4. In every handler that calls `_reply(update, text)` with AI or shell output, wrap: `text = self._redactor.redact(text)`.

> Do **not** redact inside the module-level `_reply()` function itself — it would require threading the redactor through all callers including those that post safe bot messages (e.g. help text).

---

### Step 4 — `src/platform/slack.py`: apply redaction to Slack output

Same pattern:

1. In `SlackBot.__init__`, create `self._redactor = SecretRedactor(settings)`.
2. In `_reply()`, `_send()`, and `_edit()`, redact `text` before posting.
3. In `_stream_to_slack()`, redact the `display` variable before each `_edit()` call.

---

### Step 5 — `src/executor.py`: redact git commit commands

Modify `run_shell()` to accept an optional `SecretRedactor` and apply
`redact_git_commit_cmd()` before execution:

```python
async def run_shell(cmd: str, max_chars: int, redactor: SecretRedactor | None = None) -> str:
    if redactor:
        cmd = redactor.redact_git_commit_cmd(cmd)
    proc = await asyncio.create_subprocess_shell(...)
```

> **All call sites of `run_shell()` that should pass the redactor** (requires updating these lines in both `src/bot.py` and `src/platform/slack.py`):
>
> | File | Approx. line | Context |
> |------|-------------|---------|
> | `src/bot.py` | 244 | `cmd_run` handler |
> | `src/bot.py` | 268 | `cmd_diff` handler |
> | `src/bot.py` | 285 | `cmd_diff` handler (log variant) |
> | `src/bot.py` | 434 | `cmd_log` handler |
> | `src/platform/slack.py` | 520 | `_cmd_run` |
> | `src/platform/slack.py` | 548 | `_cmd_diff` |
> | `src/platform/slack.py` | 567 | `_cmd_diff` (log variant) |
> | `src/platform/slack.py` | 711 | `_cmd_log` |
>
> Since `SecretRedactor` is instantiated on `self`, pass `self._redactor` at each call site. The `redactor` parameter is optional (`None` default) so any unmodified call sites (e.g. in unit tests) continue to work without change.

---

### Step 6 — `src/main.py`: install git commit-msg hook

At startup (after repo clone), install a `commit-msg` git hook in `REPO_DIR` that
redacts secrets from commit messages. This covers commits made by the AI subprocess
(Copilot/Codex `--allow-all`) that bypass `run_shell()`:

```python
async def _install_commit_msg_hook(settings: Settings) -> None:
    """Install a git commit-msg hook that strips secrets from commit messages.

    Installed unconditionally (even when ALLOW_SECRETS=true) because git history
    is permanent — a secret written to a commit message cannot be easily removed.
    """
    hook_path = REPO_DIR / ".git" / "hooks" / "commit-msg"
    secrets = SecretRedactor._collect_secrets(settings)
    if not secrets:
        return
    # Use a Python script instead of sed to avoid escaping pitfalls.
    # re.escape() is for Python regex, NOT for sed — secrets containing
    # the sed delimiter (|) or backslashes would break a sed-based hook.
    escaped_secrets = ", ".join(repr(s) for s in secrets)
    hook_script = f"""#!/usr/bin/env python3
import pathlib, sys
msg_file = pathlib.Path(sys.argv[1])
text = msg_file.read_text()
for secret in [{escaped_secrets}]:
    text = text.replace(secret, "[REDACTED]")
msg_file.write_text(text)
"""
    hook_path.write_text(hook_script)
    hook_path.chmod(0o755)
    logger.info("Installed commit-msg hook for secret redaction")
```

> **Note**: The hook uses a Python script (not `sed`) to avoid shell escaping pitfalls —
> `re.escape()` escapes for Python regex, not for `sed` patterns, and secrets containing
> the `sed` delimiter (`|`, `/`) or backslashes would break a `sed`-based hook. Python
> `str.replace()` is safe for arbitrary secret values. Pattern-based redaction is not
> included in the hook to avoid over-matching in commit messages. Value-based is sufficient
> because the AI subprocess has access only to the same env vars we know about.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add `allow_secrets: bool = False` to `BotConfig` |
| `src/redact.py` | **Create** | `SecretRedactor` class with value-based + pattern-based redaction |
| `src/bot.py` | **Edit** | Instantiate `SecretRedactor`, apply `redact()` on all outgoing text |
| `src/platform/slack.py` | **Edit** | Instantiate `SecretRedactor`, apply `redact()` on all outgoing text |
| `src/executor.py` | **Edit** | Accept optional `SecretRedactor`, redact git commit commands |
| `src/main.py` | **Edit** | Install `commit-msg` git hook at startup |
| `README.md` | **Edit** | Add `ALLOW_SECRETS` to env var table |
| `docs/features/secret-redaction.md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Add item 1.7 and mark done after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `re` | ✅ stdlib | No new dependency |

---

## Test Plan

### `tests/unit/test_redact.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_redact_github_pat` | GitHub PAT (`ghp_...`) is replaced with `[REDACTED]` |
| `test_redact_slack_token` | Slack bot/app tokens (`xoxb-...`, `xapp-...`) are redacted |
| `test_redact_openai_key` | OpenAI API key (`sk-...`) is redacted |
| `test_redact_bearer_header` | `Bearer` token in Authorization header is redacted |
| `test_redact_url_with_creds` | `https://user:pass@host` is redacted |
| `test_redact_known_value` | Exact env var value from config is redacted |
| `test_redact_multiple_secrets` | Text with several secrets has all of them redacted |
| `test_redact_no_false_positive` | Normal text (e.g. `sk-ip` or `ghp_` alone) is not over-redacted |
| `test_redact_disabled` | When `ALLOW_SECRETS=true`, no redaction occurs |
| `test_redact_empty_text` | Empty string returns empty string |
| `test_redact_git_commit_cmd` | `git commit -m "token=ghp_..."` has the token redacted |
| `test_redact_non_git_cmd` | Non-git commands pass through unmodified |
| `test_short_values_ignored` | Secret values shorter than 8 chars are not added to known list |

### `tests/unit/test_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_ai_response_redacted` | AI response containing a secret is redacted before `edit_text()` |
| `test_allow_secrets_bypasses_redaction` | `ALLOW_SECRETS=true` lets secrets through |

### `tests/unit/test_slack_bot.py` additions

| Test | What it checks |
|------|----------------|
| `test_slack_reply_redacted` | `_reply()` redacts secrets before `chat_postMessage()` |
| `test_slack_stream_redacted` | Streaming edits redact secrets from intermediate chunks |

---

## Documentation Updates

### `README.md`

Add to the environment variables table:

```markdown
| `ALLOW_SECRETS` | `false` | Set `true` to allow secrets in AI responses (default: redacted). |
```

### `.github/copilot-instructions.md`

Add a bullet under Key Conventions:

```markdown
- **Secret redaction**: `src/redact.py` — `SecretRedactor` redacts tokens/keys from
  outgoing messages. Controlled by `ALLOW_SECRETS` env var (default `false`). Always
  import and use the redactor from the platform output methods.
```

### `docs/roadmap.md`

Add item 1.7 under Technical Debt.

---

## Version Bump

**Expected bump for this feature**: `MINOR` — adds a new env var with a safe default
that hardens security without breaking existing deployments.

---

## Edge Cases and Open Questions

1. **Partial secret in streaming chunk** — A token could be split across two streaming
   chunks (e.g. `ghp_Ie5V` in chunk 1, `lZH0OpX...` in chunk 2). The pattern-based
   regex would miss the split token. Mitigation: the final message edit always runs
   redaction on the full accumulated text, so the complete token is caught. The partial
   exposure lasts at most one throttle cycle (≤1s default). Acceptable risk.

2. **False positives** — Pattern-based regexes could match non-secret strings. Mitigated
   by requiring minimum lengths (20+ chars) and specific prefixes. The `ALLOW_SECRETS=true`
   escape hatch is available for environments where false positives are a problem.

3. **AI referencing secrets in summarization** — `summarize_if_long()` sends raw text to
   the AI. The AI sees the secret internally. The summarized response is redacted before
   reaching the user. Acceptable because the AI subprocess already has full env access.

4. **Secrets not in config** — If a user sets custom env vars (e.g. `MY_CUSTOM_TOKEN`),
   value-based redaction won't catch them. Pattern-based redaction will catch them only
   if they match a known format. Documented limitation.

5. **`gate restart` interaction** — `SecretRedactor` is stateless and instantiated at
   startup. A restart picks up any new env vars. No cleanup needed.

6. **Git hook persistence** — The `commit-msg` hook is written to `REPO_DIR/.git/hooks/`.
   `gate sync` calls `repo.pull()` (fetch + merge), which does *not* wipe `.git/hooks/`,
   so the hook persists across syncs. The hook would only be lost if the repo were
   manually deleted and re-cloned, in which case `_install_commit_msg_hook()` in
   `main.py` would reinstall it on the next container startup.

7. **Commit messages from AI subprocess** — Copilot/Codex with `--allow-all` can run
   `git commit` directly. The `commit-msg` git hook catches these. Pattern-based
   redaction is not in the hook (to avoid over-matching complexity), but value-based is
   sufficient for known secrets.

8. **`git -C <path> commit` variant** — The AI may invoke `git -C /repo commit -m "..."`.
   `redact_git_commit_cmd()` must also check for `"git -C"` in addition to `"git commit"`
   and `"git -c"` to catch this invocation style.

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] `ALLOW_SECRETS=false` (default): all outgoing messages have known secret values and
      common secret patterns replaced with `[REDACTED]`.
- [ ] `ALLOW_SECRETS=true`: secrets pass through unredacted.
- [ ] Git commit messages authored inside the container have secrets redacted via
      `commit-msg` hook. The hook is installed even when `ALLOW_SECRETS=true`, because
      git history is permanent and leaking secrets there is irreversible. (Step 6 code
      installs unconditionally — only the *output* redaction is gated on `allow_secrets`.)
- [ ] Streaming responses redact each intermediate edit and the final message.
- [ ] Both Telegram and Slack platforms apply redaction.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` updated with `ALLOW_SECRETS` env var.
- [ ] `docs/roadmap.md` entry added.
- [ ] No false positives on common English text (verified by test).
- [ ] Feature works with all AI backends (`copilot`, `codex`, `api`).
