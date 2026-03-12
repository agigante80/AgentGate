# How to Run Multiple Agents in a Slack Workspace

This guide shows how to run multiple AgentGate instances as specialised AI agents in a single Slack workspace. We use the AgentGate project itself as the working example.

## What you'll set up

Three agents, one `#agentgate` Slack channel:

| Agent | Trigger prefix | Backend | Skills file |
|-------|---------------|---------|-------------|
| `@GateCode` — Developer | `dev` | Copilot | `skills/dev-agent.md` |
| `@GateSec` — Security | `sec` | Anthropic Claude | `skills/sec-agent.md` |
| `@GateDocs` — Docs writer | `docs` | OpenAI GPT-4o | `skills/docs-agent.md` |

**Prerequisites**: A Slack workspace where you can install apps, Docker, and the credentials for at least one AI backend.

---

## How agents trigger

Agents listen to ALL messages in the channels they're in. The **prefix** is the trigger — not an @-mention.

```
dev explain the history module      ← @GateCode responds
sec review src/executor.py          ← @GateSec responds
docs write a README for this func   ← @GateDocs responds
```

With `PREFIX_ONLY=true` (required for multi-agent), each bot silently ignores messages that don't start with its prefix. This prevents all three bots answering the same message.

---

## Agent isolation and awareness

Each agent is an independent container with no awareness of the others:

| Question | Answer |
|----------|--------|
| Do agents see each other's replies? | No — each has its own isolated SQLite history DB |
| Do agents respond to each other's messages? | No by default — bots ignore bot messages |
| Can agents request work from each other? | Yes, via `TRUSTED_AGENT_BOT_IDS` (see below) |
| Do agents respond to `@here` or `@channel`? | No — `PREFIX_ONLY=true` ignores these |

---

## Agent-to-agent requests

You can configure agents to delegate work to each other. For example, after `@GateCode` writes a fix, it can automatically ask `@GateSec` to review it.

**How it works:**

1. You add each agent's `bot_id` to the other agents' `TRUSTED_AGENT_BOT_IDS` list
2. A trusted agent's message that starts with the receiving bot's prefix is processed as a command
3. The sending agent's skills file instructs the AI when and how to format a delegation request

**Finding a bot's `bot_id`**: You don't need to. Use the bot's **display name** (e.g. `"GateCode"`) directly in `TRUSTED_AGENT_BOT_IDS` — AgentGate resolves it to the internal `bot_id` automatically at startup via the Slack API. This works even when each agent runs in its own independent container, since `users.list` is workspace-scoped.

**Skills file delegation example** (from `skills/dev-agent.md`):
> "When your response involves security-sensitive changes, append at the end: `sec review: <description>`"

This results in @GateCode posting `sec review: auth bypass fix in src/bot.py line 42` in the channel — which @GateSec picks up and processes.

**Loop prevention**: Trusted agent messages can ONLY trigger named prefix commands (`sec review`, `sec scan`, etc.). They are never forwarded to the AI pipeline, so there are no runaway chains.

---

## Step 1 — Create Skills Files

Clone or copy the ready-made skills files from `skills/` in this repository:

```bash
# These files are already in the repo:
skills/dev-agent.md    # Developer persona — Python/AgentGate stack
skills/sec-agent.md    # Security engineer — STRIDE, OWASP, AgentGate threat vectors
skills/docs-agent.md   # Technical writer — AgentGate doc conventions
```

You can customise these files to fit your team. For inspiration, see:
- [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) — structured role-based personas
- [f/awesome-chatgpt-prompts](https://github.com/f/awesome-chatgpt-prompts) — large community prompt library
- [danielmiessler/fabric](https://github.com/danielmiessler/fabric) — composable system prompts
- [Anthropic's prompt library](https://docs.anthropic.com/en/resources/prompt-library/library)

---

## Step 2 — Create Slack Apps (repeat for each agent)

The fastest way is to use an **app manifest** — one paste creates the app with all scopes and events pre-configured.

### 2a — Create the app from a manifest

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Select your workspace → paste the manifest for each agent below → **Next** → **Create**

**GateCode** (`dev` prefix — Developer agent):

```json
{
  "display_information": { "name": "GateCode" },
  "features": {
    "bot_user": { "display_name": "GateCode", "always_online": false }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "channels:history", "groups:history", "im:history", "mpim:history",
        "chat:write", "files:read", "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "message.channels", "message.groups", "message.im", "message.mpim"
      ]
    },
    "interactivity": { "is_enabled": true },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

**GateSec** (`sec` prefix — Security agent):

```json
{
  "display_information": { "name": "GateSec" },
  "features": {
    "bot_user": { "display_name": "GateSec", "always_online": false }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "channels:history", "groups:history", "im:history", "mpim:history",
        "chat:write", "files:read", "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "message.channels", "message.groups", "message.im", "message.mpim"
      ]
    },
    "interactivity": { "is_enabled": true },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

**GateDocs** (`docs` prefix — Docs agent):

```json
{
  "display_information": { "name": "GateDocs" },
  "features": {
    "bot_user": { "display_name": "GateDocs", "always_online": false }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "channels:history", "groups:history", "im:history", "mpim:history",
        "chat:write", "files:read", "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "message.channels", "message.groups", "message.im", "message.mpim"
      ]
    },
    "interactivity": { "is_enabled": true },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

### 2b — After creating each app

1. **Settings → Basic Information** → scroll to **App-Level Tokens** → **Generate Token and Scopes** → name it anything → scope: `connections:write` → **Generate** → copy the token (`xapp-...`)
2. **Install App** → **Install to workspace** → **Allow** → copy the Bot User OAuth Token (`xoxb-...`)

Repeat for all three apps.

> **Manual setup reference**: If you prefer not to use a manifest, the equivalent manual steps are: Enable Socket Mode, add bot events (`message.channels`, `message.groups`, `message.im`, `message.mpim`) under Event Subscriptions, add bot scopes (`channels:history`, `groups:history`, `im:history`, `mpim:history`, `chat:write`, `files:read`, `users:read`) under OAuth & Permissions, then install to workspace.

---

## Step 3 — Add Bots to the Channel

Each bot must be explicitly added to the Slack channel before it can receive messages there.

For each of the three bots:

1. Open the channel in Slack → click the channel name at the top → **Integrations** tab
2. Click **Add an App** → find and select the bot (GateCode / GateSec / GateDocs)

All three bots should now appear in the channel's integrations list.

---

## Step 4 — Create `.env` Files

```bash
# .env.dev
PLATFORM=slack
SLACK_BOT_TOKEN=xoxb-dev-...
SLACK_APP_TOKEN=xapp-dev-...
SLACK_CHANNEL_ID=C0123456789
BOT_CMD_PREFIX=dev
PREFIX_ONLY=true
GITHUB_REPO=agigante80/AgentGate
GITHUB_REPO_TOKEN=ghp_...
AI_CLI=copilot
AI_MODEL=claude-sonnet-4-5
COPILOT_SKILLS_DIRS=/skills
TRUSTED_AGENT_BOT_IDS=["GateSec","GateDocs"]   # display names of @GateSec and @GateDocs
```

```bash
# .env.sec
PLATFORM=slack
SLACK_BOT_TOKEN=xoxb-sec-...
SLACK_APP_TOKEN=xapp-sec-...
SLACK_CHANNEL_ID=C0123456789
BOT_CMD_PREFIX=sec
PREFIX_ONLY=true
GITHUB_REPO=agigante80/AgentGate
GITHUB_REPO_TOKEN=ghp_...
AI_CLI=api
AI_PROVIDER=anthropic
AI_API_KEY=sk-ant-...
AI_MODEL=claude-opus-4-5
SYSTEM_PROMPT_FILE=/skills/sec-agent.md
TRUSTED_AGENT_BOT_IDS=["GateCode","GateDocs"]   # display names of @GateCode and @GateDocs
```

```bash
# .env.docs
PLATFORM=slack
SLACK_BOT_TOKEN=xoxb-docs-...
SLACK_APP_TOKEN=xapp-docs-...
SLACK_CHANNEL_ID=C0123456789
BOT_CMD_PREFIX=docs
PREFIX_ONLY=true
GITHUB_REPO=agigante80/AgentGate
GITHUB_REPO_TOKEN=ghp_...
AI_CLI=api
AI_PROVIDER=openai
AI_API_KEY=sk-...
AI_MODEL=gpt-4o
SYSTEM_PROMPT_FILE=/skills/docs-agent.md
TRUSTED_AGENT_BOT_IDS=["GateCode","GateSec"]    # display names of @GateCode and @GateSec
```

> **Note**: `COPILOT_SKILLS_DIRS` loads skills for the Copilot CLI backend. `SYSTEM_PROMPT_FILE` loads skills for the `api` backend (OpenAI / Anthropic / Ollama). Both read the same markdown file format.
>
> **Note**: `TRUSTED_AGENT_BOT_IDS` accepts **display names** (e.g. `"GateCode"`) or raw `B`-prefixed bot IDs. Names are resolved automatically at startup — no manual ID lookup needed.
>
> **Note**: `SLACK_CHANNEL_ID` is required — without it the bot cannot post its 🟢 Ready message on startup. To find the Channel ID: click the channel name at the top of the channel → **Channel details** opens → the ID is shown at the bottom of the panel (starts with `C`). See [`docs/guides/slack-setup.md`](slack-setup.md) for the full single-agent setup guide.

---

## Step 5 — Docker Compose

```yaml
# docker-compose.multi-agent.yml

services:

  dev:
    image: ghcr.io/agigante80/agentgate:latest
    restart: unless-stopped
    env_file: .env.dev
    volumes:
      - repo_dev:/repo
      - data_dev:/data
      - ./skills/dev-agent.md:/skills/dev-agent.md:ro
    labels:
      agentgate.agent: dev

  sec:
    image: ghcr.io/agigante80/agentgate:latest
    restart: unless-stopped
    env_file: .env.sec
    volumes:
      - repo_sec:/repo
      - data_sec:/data
      - ./skills/sec-agent.md:/skills/sec-agent.md:ro
    labels:
      agentgate.agent: sec

  docs:
    image: ghcr.io/agigante80/agentgate:latest
    restart: unless-stopped
    env_file: .env.docs
    volumes:
      - repo_docs:/repo
      - data_docs:/data
      - ./skills/docs-agent.md:/skills/docs-agent.md:ro
    labels:
      agentgate.agent: docs

volumes:
  repo_dev:
  data_dev:
  repo_sec:
  data_sec:
  repo_docs:
  data_docs:
```

Each agent has its own named volumes so histories and repo clones are fully isolated.

---

## Step 6 — Launch and Verify

```bash
# Launch all three agents
docker compose -f docker-compose.multi-agent.yml up -d

# Check they're all running
docker compose -f docker-compose.multi-agent.yml ps

# Tail a specific agent's logs
docker compose -f docker-compose.multi-agent.yml logs -f sec
```

Each bot posts a 🟢 Ready message on startup. Test each:

```
dev what's the architecture of the history module?
sec review src/executor.py for injection vulnerabilities
docs write a one-paragraph overview of the Slack integration
```

---

## Channel strategy

| Strategy | Best for |
|----------|----------|
| **Single channel, all agents** (`SLACK_CHANNEL_ID` all the same) | Small team, easy discovery, cross-pollination (seeing `sec` flag what `dev` just wrote) |
| **Dedicated channel per agent** (`#agentgate-dev`, `#agentgate-sec`, `#agentgate-docs`) | Clear separation, reduced noise, sensitive security queries stay private |
| **Shared + specialised** (`#agentgate` for general + private channels for sec) | Balanced — recommended for teams handling sensitive code |

---

## Customising agent personas

Edit the skills files in `skills/` to change each agent's behaviour. The format follows the [agency-agents](https://github.com/msitarzewski/agency-agents) structure:

```markdown
---
name: My Agent
emoji: 🤖
---

## Identity
What this agent is and how it thinks.

## Core Mission
What it's here to do.

## Critical Rules
Non-negotiable constraints.

## Workflow
Step-by-step process for typical tasks.
```

For the Copilot backend, all files in `COPILOT_SKILLS_DIRS` are loaded at subprocess spawn time — just edit the file, no restart needed. For the `api` backend, `SYSTEM_PROMPT_FILE` is read at container startup — restart the container after editing the file.
