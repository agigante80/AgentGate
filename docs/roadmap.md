# AgentGate — Roadmap

> Last updated: 2026-03-13

Items ordered by priority. Each item links to a feature doc with full design detail.

---

## Technical Debt

| # | Item | Detail |
|---|------|--------|
| ✅ 1.1 | Improve test coverage for error paths in `bot.py`, `main.py`, `ai/session.py`, `ai/direct.py` | [→ features/test-coverage.md](features/test-coverage.md) |
| 1.2 | npm globals (`@github/copilot-cli`, `@openai/codex`) not covered by Dependabot | [→ features/npm-dependabot.md](features/npm-dependabot.md) |
| 1.3 | History storage hardcoded to SQLite — introduce `ConversationStorage` ABC | [→ features/history-storage.md](features/history-storage.md) |
| 1.4 | `AIConfig` mixes Copilot, Codex, and Direct API fields in one flat struct | [→ features/aiconfig-split.md](features/aiconfig-split.md) |
| 1.5 | Shell injection in `gate diff` + auth bypass with empty `SLACK_CHANNEL_ID` | [→ features/input-sanitization.md](features/input-sanitization.md) |
| 1.6 | AI prompt injection hardening — frame untrusted content, restrict system-prompt paths, harden history replay | [→ features/prompt-injection.md](features/prompt-injection.md) |

---

## Features

| # | Item | Detail |
|---|------|--------|
| 2.1 | ✅ **[HIGH]** Post final AI response as new message so other agents can react to it (`SLACK_DELETE_THINKING`) | [→ features/slack-final-response-new-message.md](features/slack-final-response-new-message.md) |
| 2.2 | ✅ **[HIGH]** Agent-to-agent delegation via `[DELEGATE: prefix message]` sentinel blocks | [→ features/slack-agent-delegation.md](features/slack-agent-delegation.md) |
| 2.3 | **[HIGH]** Thread reply mode — opt-in per-agent via `SLACK_THREAD_REPLIES=true` | [→ features/slack-thread-replies.md](features/slack-thread-replies.md) |
| 2.4 | `/gate schedule` — run shell commands or AI prompts on a recurring schedule | [→ features/schedule.md](features/schedule.md) |
| 2.5 | Gemini CLI backend — `AI_CLI=gemini` backed by Google's official Gemini CLI | [→ features/gemini-cli-backend.md](features/gemini-cli-backend.md) |
| 2.6 | `/gate switch` — hot-swap the AI backend at runtime without restart | [→ features/switch-backend.md](features/switch-backend.md) |
| 2.7 | `/gate file` — send files from `/repo` to chat, or receive uploads into `/repo` | [→ features/file-transfer.md](features/file-transfer.md) |
| 2.8 | Proactive alerts — notify chat on file changes or log keyword matches | [→ features/proactive-alerts.md](features/proactive-alerts.md) |
| 2.9 | Copilot session pre-warming — reduce repeated context-setup overhead | [→ features/copilot-prewarm.md](features/copilot-prewarm.md) |
| 2.10 | `HISTORY_TURNS` env var + `/gate context` to cap injected history length | [→ features/history-turns.md](features/history-turns.md) |
| 2.11 | Voice transcription — local offline Whisper (`WHISPER_PROVIDER=local`) | [→ features/whisper-local.md](features/whisper-local.md) |
| 2.12 | Voice transcription — Google Speech-to-Text (`WHISPER_PROVIDER=google`) | [→ features/whisper-google.md](features/whisper-google.md) |
| 2.13 | Lightweight web dashboard — read-only HTTP status page inside the container | [→ features/web-dashboard.md](features/web-dashboard.md) |
| 2.14 | ✅ AI response feedback — proactive "Still thinking…" ticker and configurable per-backend timeout | Implemented in v0.8.0 |

