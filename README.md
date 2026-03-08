# AgentGate

**Your AI CLI, anywhere.**

Chat with your AI coding assistant (GitHub Copilot, Codex, OpenAI, Anthropic) via Telegram or Slack — one Docker container per project, zero context switching.

> ✅ Works with **Telegram** | ✅ Works with **Slack** | ✅ Tested on **Synology NAS** | ✅ Tested with **GitHub Copilot**

---

## Features

- 🤖 **Pluggable AI backends** — Copilot CLI, Codex CLI, OpenAI, Anthropic, Ollama
- 💬 **Multi-platform** — Telegram or Slack (Socket Mode); choose via `PLATFORM=telegram|slack`
- 📁 **Repo-aware** — clones your project on startup; AI runs in that directory
- 💬 **Conversation history** — per-chat SQLite store, injected as context
- ⚡ **Streaming responses** — message updates as the AI types (configurable)
- 🔀 **Multi-turn sessions** — SQLite history injected for stateless backends; Direct API maintains native state
- 🐳 **One container per project** — fully isolated, all config via env vars
- 🔒 **Secure** — non-root container, allowlist by chat/user ID, confirmation for destructive shell commands

---

## Quick Start

```bash
cp .env.example .env
# fill in TG_BOT_TOKEN, TG_CHAT_ID, GITHUB_REPO_TOKEN, GITHUB_REPO, AI_CLI
cp docker-compose.yml.example docker-compose.yml
docker compose up -d
```

The bot sends a 🟢 Ready message to your chat when it's up.

### Using the pre-built image

A Docker image is published automatically to GitHub Container Registry on every push:

| Branch/event | Image tag |
|---|---|
| Push to `develop` or `development` | `ghcr.io/agigante80/agentgate:develop` + `ghcr.io/agigante80/agentgate:development` |
| Push to `main` | `ghcr.io/agigante80/agentgate:latest` + `ghcr.io/agigante80/agentgate:main` |
| Version release | `ghcr.io/agigante80/agentgate:X.Y.Z` |

```bash
# Latest stable
docker pull ghcr.io/agigante80/agentgate:latest

# Latest development build
docker pull ghcr.io/agigante80/agentgate:develop

# Specific version
docker pull ghcr.io/agigante80/agentgate:0.4.0
```

In your `docker-compose.yml`, replace the `build:` section with:

```yaml
services:
  bot:
    image: ghcr.io/agigante80/agentgate:latest
```

---

## Bot Commands

Commands use a configurable prefix (`BOT_CMD_PREFIX`, default `gate`):

| Command | Description |
|---|---|
| `/gate run <cmd>` | Run a shell command in the repo |
| `/gate sync` | `git pull` |
| `/gate git` | `git status` + last 3 commits |
| `/gate status` | Show active AI requests |
| `/gate clear` | Clear conversation history |
| `/gate restart` | Restart the AI backend session |
| `/gate info` | Repo, branch, AI backend, uptime |
| `/gate help` | Full command reference + version |

**Everything else** (free text or any other `/command`) is forwarded to the AI.

Destructive shell commands (`push`, `merge`, `rm`, `force`) require inline confirmation.

---

## Startup Sequence

1. Validate env vars — fail fast with a clear error
2. Clone `GITHUB_REPO` → `/repo` (skipped if already present)
3. Auto-install deps: `package.json` → `npm install`, `pyproject.toml` → `pip install`, `go.mod` → `go mod download`
4. Initialize conversation history DB (`/data/history.db`)
5. Start AI backend session
6. Start Telegram bot → send 🟢 Ready message

---

## Environment Variables

Copy `.env.example` — it documents every variable with examples.

### Platform

| Variable | Default | Description |
|---|---|---|
| `PLATFORM` | `telegram` | `telegram` \| `slack` — selects the messaging platform |

### Required — Telegram (`PLATFORM=telegram`)

| Variable | Description |
|---|---|
| `TG_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TG_CHAT_ID` | Your Telegram chat/group ID — bot ignores all others |

### Required — Slack (`PLATFORM=slack`)

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Bot OAuth token (`xoxb-…`) from your Slack App |
| `SLACK_APP_TOKEN` | App-level token (`xapp-…`) for Socket Mode |

### Shared / Always Required

| Variable | Description |
|---|---|
| `GITHUB_REPO_TOKEN` | PAT with `repo` scope — used for git clone/push |
| `GITHUB_REPO` | `owner/repo` format |

### AI Backend

| Variable | Default | Description |
|---|---|---|
| `AI_CLI` | `copilot` | `copilot` \| `codex` \| `api` |
| `COPILOT_GITHUB_TOKEN` | — | Fine-grained PAT with **Copilot Requests** permission (required for `copilot` backend) |
| `AI_MODEL` | — | Model for any backend (e.g. `gpt-4o` for Copilot, `o3` for Codex, `claude-3-5-sonnet-20241022` for API). Codex defaults to `o3` when unset. |
| `AI_PROVIDER` | — | For `api`: `openai` \| `anthropic` \| `ollama` \| `openai-compat` |
| `AI_API_KEY` | — | API key for `codex` or `api` backends |
| `AI_BASE_URL` | — | Base URL for Ollama or compatible endpoints |
| `AI_CLI_OPTS` | — | Raw options passed verbatim to the CLI subprocess. **Empty (default) = full-auto per backend** (Copilot: `--allow-all`; Codex: `--approval-mode full-auto`). **When set, replaces the defaults entirely** — must include full-auto flags if still needed (e.g. `--allow-all --allow-url github.com`). Ignored (with a warning) when `AI_CLI=api`. |

### Bot Behaviour

| Variable | Default | Description |
|---|---|---|
| `BOT_CMD_PREFIX` | `gate` | Prefix for utility commands |
| `MAX_OUTPUT_CHARS` | `3000` | Truncate/summarize output beyond this length |
| `HISTORY_ENABLED` | `true` | Set `false` to disable conversation history storage |
| `STREAM_RESPONSES` | `true` | Set `false` to wait for full response before sending |
| `STREAM_THROTTLE_SECS` | `1.0` | Seconds between streaming message edits |
| `CONFIRM_DESTRUCTIVE` | `true` | Set `false` to skip confirmation for destructive shell commands |
| `SKIP_CONFIRM_KEYWORDS` | — | Comma-separated keywords that bypass destructive confirmation (e.g. `push,rm`) |

### Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `LOG_DIR` | — | Directory for rotating log files (empty = stdout only). Logs rotate daily, kept 14 days, gzip compressed. Mount a host volume to persist across restarts. |

> Full logging guide: **[docs/logging.md](docs/logging.md)**

```yaml
# Example: persist logs on host
volumes:
  - ./logs:/data/logs
environment:
  - LOG_DIR=/data/logs
```

### Voice Transcription

| Variable | Default | Description |
|---|---|---|
| `WHISPER_PROVIDER` | `none` | `none` \| `openai` — enables Telegram voice message transcription |
| `WHISPER_API_KEY` | — | API key for Whisper (falls back to `AI_API_KEY` when provider is `openai`) |
| `WHISPER_MODEL` | `whisper-1` | Whisper model name |

### Optional

| Variable | Description |
|---|---|
| `ALLOWED_USERS` | Comma-separated Telegram user IDs (extra allowlist, Telegram only) |
| `SLACK_CHANNEL_ID` | Restrict Slack bot to a single channel (e.g. `C0123456789`) |
| `SLACK_ALLOWED_USERS` | JSON array of Slack user IDs allowed to use the bot (e.g. `["U111","U222"]`) |
| `BRANCH` | Git branch to clone (default: `main`) |
| `REPO_HOST_PATH` | Host directory to bind-mount as `/repo` — persists across rebuilds |

---

## Slack Setup

> Full step-by-step guide: **[docs/slack-setup.md](docs/slack-setup.md)**

Quick summary:

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `channels:history`, `groups:history`, `im:history`, `mpim:history`, `files:read`
3. **Socket Mode** → Enable → Generate token (`connections:write` scope) → `SLACK_APP_TOKEN` (`xapp-…`)
4. **Event Subscriptions** → Enable → Subscribe to bot events: `message.channels`, `message.groups`, `message.im`, `message.mpim` → Save
5. **OAuth & Permissions** → **Install to Workspace** → copy Bot OAuth Token → `SLACK_BOT_TOKEN` (`xoxb-…`)
6. In Slack: `/invite @YourBotName` in a channel → copy Channel ID → `SLACK_CHANNEL_ID`
7. Set `PLATFORM=slack` in `.env` and restart

> ⚠️ After any scope or event change, **reinstall the app** (step 5) to get a fresh token.

> ⚠️ **Do not use `/` prefix in Slack** — Slack intercepts `/cmd` as a native slash command. Use `gate cmd` instead (`gate help`, `gate sync`, etc.). If you need to send a message starting with `/`, prepend a space: ` /cmd`.

---

## One Bot per Project

Each project is its own Docker Compose stack with its own `.env`:

```
projects/
├── vpn-sentinel/
│   ├── docker-compose.yml
│   └── .env            ← TG_BOT_TOKEN, GITHUB_REPO=owner/vpn-sentinel
└── my-api/
    ├── docker-compose.yml
    └── .env            ← TG_BOT_TOKEN, GITHUB_REPO=owner/my-api
```

Run them side by side — fully isolated, separate Telegram bots.

---

## Persistent Repo (no re-cloning on restart)

Set `REPO_HOST_PATH` in `.env` to a directory on your machine:

```env
REPO_HOST_PATH=/home/me/projects/VPNSentinel
```

Docker bind-mounts it to `/repo`. The bot clones once, reuses forever.

---

## AI Backends

### GitHub Copilot CLI (default)

Requires a **fine-grained PAT** with the *Copilot Requests* permission. Classic `ghp_` tokens are **not** supported.

```env
AI_CLI=copilot
COPILOT_GITHUB_TOKEN=github_pat_...
```

### OpenAI Codex CLI

```env
AI_CLI=codex
AI_API_KEY=sk-...
AI_MODEL=o3
```

### Direct API — OpenAI / Anthropic / Ollama

```env
AI_CLI=api
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-...
AI_MODEL=claude-3-5-sonnet-20241022
```

```env
AI_CLI=api
AI_PROVIDER=ollama
AI_MODEL=llama3.2
AI_BASE_URL=http://host.docker.internal:11434
```

---

## Security

- Bot responds **only** to `TG_CHAT_ID`
- `ALLOWED_USERS` adds per-user filtering inside the allowed chat
- Destructive shell ops require confirmation
- Non-root user inside container
- Fine-grained GitHub token scoped to one repo

---

## License

MIT
