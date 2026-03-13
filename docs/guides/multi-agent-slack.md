# How to Run Multiple Agents in a Slack Workspace

This guide shows how to run multiple AgentGate instances as specialised AI agents in a single Slack workspace. We use the AgentGate project itself as the working example.

See also: docs/features/slack-final-response-new-message.md, docs/features/slack-agent-delegation.md, docs/features/slack-thread-replies.md

## What you'll set up

Three agents, one `#agentgate` Slack channel:

| Agent | Trigger prefix | Backend | Model |
|-------|---------------|---------|-------|
| `@GateCode` — Developer | `dev` | Copilot | `claude-sonnet-4.6` |
| `@GateSec` — Security | `sec` | Copilot | `claude-opus-4.6` |
| `@GateDocs` — Docs writer | `docs` | Copilot | `gpt-5-mini` |

**Prerequisites**: A Slack workspace where you can install apps, Docker, and the credentials for at least one AI backend.

---

## How agents trigger

Agents respond to two types of messages:

**Prefix trigger** — messages starting with the agent's prefix:
```
dev explain the history module      ← @GateCode responds
sec review src/executor.py          ← @GateSec responds
docs write a README for this func   ← @GateDocs responds
```

**@mention trigger** — directly @mentioning the bot anywhere in a message:
```
@GateCode what's the status of the auth refactor?   ← GateCode responds (bypasses PREFIX_ONLY)
@GateSec are you available?                          ← GateSec responds
```

With `PREFIX_ONLY=true` (required for multi-agent), each bot silently ignores unprefixed messages from human users. @mentions always get a response regardless of `PREFIX_ONLY`.

---

## Agent isolation and awareness

Each agent is an independent container with its own clone of the repo and history DB:

| Question | Answer |
|----------|--------|
| Do agents see each other's replies? | No — each has its own isolated SQLite history DB |
| Do agents respond to each other's messages? | No by default — bots ignore bot messages |
| Can agents request work from each other? | Yes, via `TRUSTED_AGENT_BOT_IDS` (see below) |
| Do agents respond to `@here` or `@channel`? | No — `PREFIX_ONLY=true` ignores these |
| Does each agent know its teammates? | **Yes** — team context is auto-generated at startup |

### Auto-generated team context

At startup, each agent automatically builds a team context string and prepends it to every AI prompt. This means bots always know who they are, who their teammates are, and how to address them — without any manual configuration:

```
You are GateCode (prefix: dev).
Your team in this Slack workspace:
  - GateSec (prefix: sec) — users address them with: sec <message>
  - GateDocs (prefix: docs) — users address them with: docs <message>
Repo: agigante80/AgentGate | Branch: develop
Formatting (Slack mrkdwn): *bold* (NOT **bold**), _italic_, `inline code`, ```code blocks```, >blockquote, - bullet list
```

This context is derived automatically from `BOT_CMD_PREFIX`, `TRUSTED_AGENT_BOT_IDS` (including their prefixes), and `GITHUB_REPO`/`BRANCH`. No additional env var is needed.

> **Why team context and not skills files?** Skills files (`COPILOT_SKILLS_DIRS`) are loaded by **both Slack and Telegram** deployments. Platform-specific instructions (like Slack mrkdwn syntax) must go in the team context, which is Slack-only code. This keeps skills files platform-neutral and reusable.

### Optional `SYSTEM_PROMPT`

You can add a `SYSTEM_PROMPT` env var to each `.env` file for agent-specific role descriptions or persona customisation. It is appended after the auto-generated team context:

```bash
SYSTEM_PROMPT=You are a security-focused code reviewer. Always check for injection vulnerabilities, insecure defaults, and missing input validation.
```

Leave it empty (default) to rely entirely on the skills files.

---

## Agent-to-agent requests

You can configure agents to delegate work to each other. For example, after `@GateCode` writes a fix, it can automatically ask `@GateSec` to review it.

### Delegation sentinel protocol (v0.10+)

Each agent's AI is automatically instructed (via the team context injected into every prompt) to use a structured delegation sentinel:

```
[DELEGATE: <prefix> <full message to send>]
```

The bot:
1. Strips the sentinel from the displayed response (it never appears in chat)
2. Posts `<prefix> <message>` as a new standalone channel message
3. The target agent's bot sees the message, recognises its prefix, and routes it to its AI pipeline

**Example end-to-end flow:**

```
Human: dev analyse the auth module for security issues

GateCode AI responds (displayed):
  "I've reviewed auth.py. The token generation looks weak."

Behind the scenes, GateCode also emitted:
  [DELEGATE: sec Please review auth.py — generate_token() uses random.random() instead of secrets.token_bytes()]

GateSec sees: "sec Please review auth.py — generate_token() uses …"
GateSec AI responds (new message):
  "⚠️ Confirmed: random.random() is not cryptographically secure. Use secrets.token_bytes(32)."
```

**No skills file changes needed** — delegation instructions are injected automatically via `_build_team_context()`. Both agents must have each other in `TRUSTED_AGENT_BOT_IDS`.

**Security guardrails (built-in):**
- Delegations starting with dangerous sub-commands (`run`, `sync`, `git`, `diff`, `log`, `restart`, `clear`, `confirm`) are *silently blocked* and logged — this prevents the AI from triggering arbitrary shell execution on a peer agent.
- At most 3 delegation blocks are processed per AI response (flood prevention).

**Loop prevention**: Trusted agent messages are *never* forwarded to the AI pipeline — they only trigger named prefix commands via `_dispatch()`. Delegation chains are at most one hop: human → agent A → agent B. Agent B cannot further delegate back to A.

**How the routing works:**

1. Each agent's `TRUSTED_AGENT_BOT_IDS` lists its teammates by display name and prefix (e.g. `"GateCode:dev"`)
2. AgentGate resolves each name to an internal Slack `bot_id` at startup via `users.list`
3. When a message arrives from a trusted bot, it is dispatched via `_dispatch()` — only known prefix sub-commands are accepted
4. The AI pipeline is **never** reached for trusted bot messages

**Finding a bot's `bot_id`**: You don't need to. Use the bot's **display name and prefix** (e.g. `"GateCode:dev"`) directly in `TRUSTED_AGENT_BOT_IDS` — AgentGate resolves the name to the internal `bot_id` automatically at startup via the Slack API. The `:prefix` suffix tells each agent how to address its teammates in the auto-generated team context.

**Format**: `"DisplayName:prefix"` (e.g. `"GateSec:sec"`). The `:prefix` part is optional but strongly recommended — without it the team context won't include how to address that agent.

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

> ⚠️ **If you already created the app and need to add a scope** (e.g. `users:read`): go to **OAuth & Permissions** → **Bot Token Scopes** → add the scope → then **Install App** → **Install to workspace** → **Allow** to get a fresh token. Update `SLACK_BOT_TOKEN` in your `.env` with the new `xoxb-...` value.

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
AI_MODEL=claude-sonnet-4.6
COPILOT_GITHUB_TOKEN=ghp_...
COPILOT_SKILLS_DIRS=/repo/skills
TRUSTED_AGENT_BOT_IDS=["GateSec:sec","GateDocs:docs"]   # name:prefix of each teammate
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
AI_CLI=copilot
AI_MODEL=claude-opus-4.6
COPILOT_GITHUB_TOKEN=ghp_...
COPILOT_SKILLS_DIRS=/repo/skills
TRUSTED_AGENT_BOT_IDS=["GateCode:dev","GateDocs:docs"]   # name:prefix of each teammate
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
AI_CLI=copilot
AI_MODEL=gpt-5-mini
COPILOT_GITHUB_TOKEN=ghp_...
COPILOT_SKILLS_DIRS=/repo/skills
TRUSTED_AGENT_BOT_IDS=["GateCode:dev","GateSec:sec"]    # name:prefix of each teammate
```

> **Note**: All agents use `AI_CLI=copilot`. `COPILOT_GITHUB_TOKEN` is required — use a GitHub Personal Access Token with Copilot access. `AI_MODEL` selects the model per agent; see [GitHub Copilot model comparison](https://docs.github.com/en/copilot/reference/ai-models/model-comparison) for the full list of available models.
>
> **Note**: `COPILOT_SKILLS_DIRS=/repo/skills` points to the `skills/` directory inside the cloned repo (`/repo` is where the container clones `GITHUB_REPO` at startup). No host copy or volume mount needed — the skills are already there.
>
> **Note**: `TRUSTED_AGENT_BOT_IDS` accepts entries in `"DisplayName:prefix"` format (e.g. `"GateSec:sec"`) or bare `B`-prefixed bot IDs. Names are resolved automatically at startup — no manual ID lookup needed. The `:prefix` suffix enables auto-generated team context so each agent knows how to address its teammates.
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
      - ./data/dev:/data
    labels:
      agentgate.agent: dev

  sec:
    image: ghcr.io/agigante80/agentgate:latest
    restart: unless-stopped
    env_file: .env.sec
    volumes:
      - repo_sec:/repo
      - ./data/sec:/data
    labels:
      agentgate.agent: sec

  docs:
    image: ghcr.io/agigante80/agentgate:latest
    restart: unless-stopped
    env_file: .env.docs
    volumes:
      - repo_docs:/repo
      - ./data/docs:/data
    labels:
      agentgate.agent: docs

volumes:
  repo_dev:
  repo_sec:
  repo_docs:
```

Each agent has its own named volume for `/repo` (the cloned git repo) and its own local `./data/<agent>/` folder for `/data` (SQLite history DB, logs). The three `data/` folders are fully isolated — no write conflicts between agents.

Skills files (`skills/`) live inside the cloned repo at `/repo/skills/` — no host copy needed. `COPILOT_SKILLS_DIRS=/repo/skills` points there directly.

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

For the Copilot backend, skills are loaded from `COPILOT_SKILLS_DIRS` at subprocess spawn time. Since they live in the cloned repo at `/repo/skills/`, you can update them with a `dev sync` (git pull) without rebuilding — just restart the container after syncing.
