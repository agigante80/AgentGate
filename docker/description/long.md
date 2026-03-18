# AgentGate

**Chat with AI coding assistants (GitHub Copilot, Codex, Gemini) via Telegram or Slack — one Docker container per project.**

Run multiple specialised agents in the same workspace and let them collaborate with each other.

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/agigante80/AgentGate.git
cd AgentGate
cp .env.example .env        # fill in your tokens
cp docker-compose.yml.example docker-compose.yml

# 2. Start
docker compose up -d
```

Or pull the pre-built image directly:

```bash
# Docker Hub (stable)
docker pull agigante80/agentgate:latest

# Docker Hub (latest dev build)
docker pull agigante80/agentgate:develop

# GHCR mirror
docker pull ghcr.io/agigante80/agentgate:latest
```

---

## Supported AI backends

| Backend | `AI_CLI` value | Tested |
|---|---|---|
| GitHub Copilot CLI | `copilot` | ✅ |
| OpenAI Codex CLI | `codex` | ✅ |
| Google Gemini CLI | `gemini` | ✅ |
| Direct API (OpenAI / Anthropic / Ollama) | `api` | ⚠️ not field-tested |

---

## Key environment variables

```dotenv
# Platform: telegram (default) or slack
PLATFORM=telegram

# Telegram
TG_BOT_TOKEN=your-telegram-bot-token
TG_CHAT_ID=your-chat-id

# Slack (if PLATFORM=slack)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# GitHub repository to clone into the container
GITHUB_REPO=https://github.com/you/your-project.git
GITHUB_REPO_TOKEN=ghp_...

# AI backend
AI_CLI=copilot        # copilot | codex | gemini | api
BOT_PREFIX=gate       # command prefix, e.g. "gate help"
```

Full list of env vars: https://github.com/agigante80/AgentGate#configuration

---

## Multi-agent setup

Run three specialised agents simultaneously — each in its own container, each with its own persona and AI backend:

| Agent | Prefix | Backend | Role |
|---|---|---|---|
| GateCode | `dev` | Codex | Implementation & code review |
| GateDocs | `docs` | Gemini | Documentation & roadmap sync |
| GateSec | `sec` | Copilot | Security audits & hardening |

Message any agent from Slack: `dev explain the auth flow` or `docs summarize the roadmap`.

Full guide: https://github.com/agigante80/AgentGate/blob/main/docs/guides/multi-agent-slack.md

---

## Image tags

| Event | Tags |
|---|---|
| Push to `develop` | `:develop`, `:development`, `:X.Y.Z-dev-SHA` |
| Push to `main` | `:latest`, `:main`, `:X.Y.Z` |
| Version release | `:X.Y.Z`, `:latest` |

---

## Source & documentation

- **GitHub**: https://github.com/agigante80/AgentGate
- **Multi-agent guide**: https://github.com/agigante80/AgentGate/blob/main/docs/guides/multi-agent-slack.md
- **Issues / feedback**: https://github.com/agigante80/AgentGate/issues
