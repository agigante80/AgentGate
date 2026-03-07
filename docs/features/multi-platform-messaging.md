# Feature: Multi-Platform Messaging (Slack + Telegram)

> Status: **Planned**
> Branch: `develop`

---

## Overview

TeleAgent currently supports only Telegram as its messaging front-end. This document describes the design for adding Slack as an optional alternative, chosen via a single environment variable (`PLATFORM=telegram|slack`). The AI backends, history DB, executor, repo, and voice transcription layers need zero changes — only the messaging layer is platform-specific.

---

## Project Rename Candidates

Since the project will no longer be Telegram-only, consider renaming. Five suggestions:

| Name | Rationale |
|------|-----------|
| **AgentGate** | Gateway to AI agents; platform-agnostic; concise |
| **BotBridge** | Bridges AI CLIs to any messaging platform |
| **DevRelay** | Relays dev operations through your chat platform |
| **MeshAgent** | Agent across multiple platforms ("mesh" implies connectivity) |
| **CliMesh** | CLI-first, meshes multiple chat platforms |

Current favourite: **AgentGate** — clean, memorable, no platform name in it.

---

## Current Architecture (Telegram-only)

```
main.py ──► bot.py ──► python-telegram-bot (PTB)
                │
                ├── AIConfig / ai/factory.py   (platform-agnostic ✅)
                ├── history.py                 (platform-agnostic ✅)
                ├── executor.py                (platform-agnostic ✅)
                ├── repo.py                    (platform-agnostic ✅)
                ├── runtime.py                 (platform-agnostic ✅)
                └── transcriber.py             (platform-agnostic ✅)
```

`src/bot.py` (428 lines) and `src/main.py` (88 lines) are the only Telegram-coupled files. All other modules are already reusable.

---

## Target Architecture (Multi-Platform)

```
main.py ──► platform/factory.py ──► platform/telegram.py (PTB)
                                └──► platform/slack.py    (slack-bolt)
                     │
                     └── [shared: AI, history, executor, repo, runtime, transcriber]
```

A `MessagingAdapter` ABC encapsulates all platform-specific operations. Business logic lives in a shared `BotHandlers` class that calls `MessagingAdapter` methods.

---

## Design

### `src/platform/adapter.py` — Abstract base class

```python
from abc import ABC, abstractmethod
from typing import Any


class MessagingAdapter(ABC):
    """Platform-agnostic messaging interface."""

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> Any:
        """Send a new message; return a reference for later editing."""

    @abstractmethod
    async def edit(self, msg_ref: Any, text: str) -> None:
        """Edit a previously sent message (used during streaming)."""

    @abstractmethod
    async def send_confirm_dialog(
        self, chat_id: str, prompt: str, cmd: str
    ) -> Any:
        """Send an interactive confirm/cancel dialog."""

    @abstractmethod
    async def get_file_bytes(
        self, file_ref: Any
    ) -> tuple[bytes, str]:
        """Download a file; return (bytes, filename)."""

    @abstractmethod
    async def run(self) -> None:
        """Start the event loop (polling / socket mode)."""
```

### `src/platform/telegram.py` — Telegram adapter

Wraps current `src/bot.py` with no business logic changes. Every method delegates to PTB `Update`/`Application`. Line budget: ≤400 lines (current `bot.py` is 428 — some cleanup expected during extraction).

### `src/platform/slack.py` — Slack adapter

Implements `MessagingAdapter` using `slack-bolt[async]` in Socket Mode. All handler methods mirror the Telegram adapter's intent.

Key Slack equivalents:

| Telegram | Slack |
|----------|-------|
| `reply_text()` | `app.client.chat_postMessage(channel=...)` |
| `msg.edit_text()` | `app.client.chat_update(channel=..., ts=...)` |
| `InlineKeyboardButton` | Block Kit Actions |
| `CallbackQueryHandler` | `@app.action(...)` |
| `voice.get_file()` | `files_info()` + auth download |
| `Application.builder().token()` | `AsyncApp(token=..., app_token=...)` |
| Long polling | Socket Mode WebSocket |

---

## Slack-Specific Configuration

```python
class SlackConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    slack_bot_token: str = ""    # SLACK_BOT_TOKEN (xoxb-...)
    slack_app_token: str = ""    # SLACK_APP_TOKEN (xapp-..., for Socket Mode)
    slack_channel_id: str = ""   # SLACK_CHANNEL_ID — restricts to one channel
    allowed_users: list[str] = []  # SLACK_ALLOWED_USERS — Slack user IDs (U...)
```

The top-level `Settings` gains a `PLATFORM=telegram|slack` discriminator:

```python
class Settings(BaseSettings):
    platform: Literal["telegram", "slack"] = "telegram"
    telegram: TelegramConfig = ...
    slack: SlackConfig = ...
    ...
```

---

## Tech Guidelines (must follow during implementation)

| Rule | Detail |
|------|--------|
| **Line length** | Max 88 chars (ruff default, enforced by CI) |
| **ABCs** | Follow existing pattern: ABC in `adapter.py`, implementations in separate files (mirrors `src/ai/adapter.py` + backends) |
| **Config** | Use `pydantic-settings BaseSettings` — no raw `os.environ` in config classes |
| **No hardcoded paths** | Always import `REPO_DIR`, `DB_PATH` from `src/config.py` |
| **No duplicate logic** | Business logic (auth, AI forwarding, streaming, confirm) lives once in shared `BotHandlers` class — adapters only handle I/O |
| **Auth decorator** | Reuse `@_requires_auth` pattern — pass `chat_id` + `user_id` into the decorator rather than `Update` |
| **Tests** | Unit tests mock `MessagingAdapter`; contract test verifies both adapters satisfy the ABC; no real network calls |
| **Imports** | Platform-specific imports inside `platform/telegram.py` and `platform/slack.py` only — never in shared code |
| **Lint** | Run `ruff check src/` before committing; CI blocks on any ruff error |

---

## Slack-Specific Gotchas

### 1. Slash commands require registration
Slack slash commands are HTTP webhook endpoints that must be registered manually in the Slack App Dashboard — one per command. If `BOT_CMD_PREFIX` is user-configurable, this becomes a maintenance burden.

**Recommendation**: use plain-text prefix matching for Slack (`ta run`, `ta sync`) instead of native slash commands. Simpler, zero registration, works the same UX-wise in DMs and channels.

### 2. Socket Mode requires two tokens
- `SLACK_BOT_TOKEN` (`xoxb-...`) — standard bot token for API calls
- `SLACK_APP_TOKEN` (`xapp-...`) — required for Socket Mode (WebSocket connection)

Both must be generated from the Slack App Dashboard.

### 3. Markdown format differences
Slack uses `mrkdwn`, not Telegram Markdown. Key differences:
- Bold: `*text*` (same in both)
- Italic: `_text_` (same)
- Code inline: `` `code` `` (same)
- Code block: ` ```code``` ` (same syntax, Slack renders it differently)
- No native `parse_mode` — all text is auto-parsed by Slack

AI responses will render adequately but not identically. No automated conversion needed; the differences are cosmetic.

### 4. Streaming rate limit
Slack `chat.update` is rate-limited to ~1 call/second per channel (Tier 3). This matches the existing `STREAM_THROTTLE_SECS=1.0` default — no change needed.

### 5. Voice files
Slack audio files arrive as a URL in the event payload. Downloading requires:
```python
file_info = await client.files_info(file=file_id)
url = file_info["file"]["url_private"]
# Must use Authorization header with SLACK_BOT_TOKEN
```
Slightly more complex than Telegram's `voice.get_file()` but straightforward.

---

## Documents to Update

When this feature is implemented, the following files require updates:

| File | Change |
|------|--------|
| `README.md` | Add `PLATFORM` env var; add Slack config section; update project name if renamed; update Docker tag descriptions |
| `docker-compose.yml.example` | Add `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_CHANNEL_ID`, `PLATFORM` vars |
| `.github/copilot-instructions.md` | Update architecture diagram; add `src/platform/` module docs; update Key Conventions |
| `docs/roadmap.md` | Mark this item done / in progress |
| `docs/versioning.md` | Note new minor version (multi-platform = minor bump) |
| `requirements.txt` | Add `slack-bolt[async]>=1.18` |
| `Dockerfile` | Verify `slack-bolt` installs correctly (no native deps) |

---

## Effort Estimate

| Task | Lines | Complexity |
|------|-------|-----------|
| `src/platform/adapter.py` — `MessagingAdapter` ABC | ~50 | Low |
| `src/platform/telegram.py` — extract from `bot.py` | ~430 (move) | Low–Medium |
| Refactor `bot.py` → `BotHandlers` (remove Update coupling) | ~50 changed | Medium |
| `src/platform/slack.py` — full Slack adapter | ~350 | Medium |
| `SlackConfig` + `PLATFORM` discriminator in `Settings` | ~35 | Low |
| `main.py` platform selection | ~15 changed | Low |
| Unit tests — mock adapter + shared handlers | ~120 | Medium |
| Contract test — both adapters satisfy ABC | ~30 | Low |
| Docs (README, compose example, copilot-instructions) | ~80 | Low |
| **Total new/changed** | **~1100 lines** | **Medium** |

**Realistic timeline**: 2–3 focused development days.

---

## Out of Scope (for this feature)

- Microsoft Teams / Discord / WhatsApp — same adapter pattern applies; add later
- Multi-platform simultaneously (one instance → both Telegram and Slack) — would require running two event loops; not planned
- Slack native slash command registration automation — manual setup step documented only
