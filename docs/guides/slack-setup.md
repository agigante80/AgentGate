# Slack Setup Guide

> Platform: **Slack** (`PLATFORM=slack`)  
> Connection: Socket Mode (WebSocket — no public endpoint required)

This guide walks through creating a Slack App, configuring the required scopes and events, obtaining the tokens, and wiring them into AgentGate.

---

## 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Give it a name (e.g. `agentgate-bot`) and pick your workspace
4. Click **Create App**

---

## 2. Add Bot Token Scopes

In the left sidebar: **OAuth & Permissions** → scroll to **Scopes** → **Bot Token Scopes** → **Add an OAuth Scope**:

| Scope | Purpose |
|---|---|
| `chat:write` | Send and update messages |
| `channels:history` | Read messages in public channels the bot is in |
| `groups:history` | Read messages in private channels the bot is in |
| `im:history` | Read direct messages sent to the bot |
| `mpim:history` | Read multi-party DMs the bot is in |
| `files:read` | Download voice/audio files for Whisper transcription |

---

## 3. Enable Socket Mode and get the App-Level Token

**Enable Socket Mode** — in the left sidebar: **Settings** → **Socket Mode** → toggle **Enable Socket Mode** → **ON**.

**Generate the App-Level Token** — in the left sidebar: **Settings** → **Basic Information** → scroll to **App-Level Tokens** → **Generate Token and Scopes**:

1. Give the token a name (e.g. `socket-token`)
2. Click **Add Scope** → select `connections:write`
3. Click **Generate**
4. Copy the token — it starts with `xapp-` → this is your **`SLACK_APP_TOKEN`**

> 💡 **Shortcut**: If you create the app from a manifest (see the [multi-agent guide](multi-agent-slack.md)), Socket Mode is enabled automatically — you only need to complete the "Generate the App-Level Token" step above.

---

## 4. Subscribe to Bot Events

In the left sidebar: **Features** → **Event Subscriptions**:

1. Toggle **Enable Events** → **ON**
   - Socket Mode is active, so no Request URL is needed
2. Click **Subscribe to bot events** → **Add Bot User Event**, add all four:
   - `message.channels` — messages in public channels
   - `message.groups` — messages in private channels
   - `message.im` — direct messages to the bot
   - `message.mpim` — multi-party DMs
3. Click **Save Changes**

---

## 5. Install the App to your Workspace

In the left sidebar: **OAuth & Permissions**:

1. Click **Install to Workspace**
2. Review permissions → click **Allow**
3. Copy the **Bot User OAuth Token** — it starts with `xoxb-` → this is your **`SLACK_BOT_TOKEN`**

> ⚠️ **After any scope or event change, you must reinstall the app** (repeat this step) to get a fresh token with the updated permissions.

---

## 6. Enable Direct Messages (Messages Tab)

By default, Slack disables direct messages to bots. To allow users to DM the bot:

1. Left sidebar → **Features** → **App Home**
2. Scroll to **Show Tabs** → **Messages Tab**
3. Check ✅ **"Allow users to send Slash commands and messages from the messages tab"**
4. Click **Save** — no reinstall needed

The bot will now appear under **Apps** in the Slack sidebar and accept DMs.

---

## 7. Invite the Bot to a Channel

In your Slack workspace:

1. Open the channel you want the bot in
2. Type `/invite @YourBotName` and press Enter — or go to **Channel Settings** → **Integrations** → **Add apps** and select your bot
3. To get the **Channel ID**: click the channel name at the top to open **Channel details** → the ID is shown at the bottom of the panel (starts with `C`, e.g. `C08XXXXXXXX`) → this is your **`SLACK_CHANNEL_ID`**

---

## 8. Configure `.env`

```env
PLATFORM=slack
SLACK_BOT_TOKEN=xoxb-...          # from step 5
SLACK_APP_TOKEN=xapp-...          # from step 3
SLACK_CHANNEL_ID=C08XXXXXXXX      # from step 6 (optional — restricts to one channel)
```

Telegram vars (`TG_BOT_TOKEN`, `TG_CHAT_ID`) can be commented out or left in place — they are ignored when `PLATFORM=slack`.

All other vars (`GITHUB_REPO`, `GITHUB_REPO_TOKEN`, `COPILOT_GITHUB_TOKEN`, `AI_CLI`, `WHISPER_*`, etc.) are unchanged.

---

## 9. Start the Bot

```bash
docker compose up -d --build
```

Check logs:
```bash
docker compose logs -f
```

A healthy startup looks like:
```
[INFO] __main__: Starting platform: slack
[INFO] slack_bolt.AsyncApp: A new session (...) has been established
[INFO] slack_bolt.AsyncApp: ⚡️ Bolt app is running!
```

The bot sends a 🟢 Ready message to `SLACK_CHANNEL_ID` on startup (if set).

---

## Commands

> ⚠️ **Slack intercepts any message starting with `/` as a native slash command.**  
> AgentGate does NOT use slash commands. Always use the plain-text `gate` prefix instead (configurable via BOT_CMD_PREFIX).  
> `gate help` ✅ — `/help` ❌ (Slack will reject it as an unknown slash command)  
> If you accidentally type `/cmd`, precede it with a space (` /cmd`) to send it as text — but it's better to just use `gate`.

Commands use the configurable prefix (`BOT_CMD_PREFIX`, default `gate`) as plain-text messages — no slash command registration required:

| Message | Action |
|---|---|
| `gate help` | Show available commands |
| `gate sync` | Pull latest changes from the repo |
| `gate run <cmd>` | Run a shell command in the repo directory |
| `gate git <args>` | Run a git command |
| `gate diff` | Show current git diff |
| `gate log` | Show recent git log |
| `gate status` | Show bot status (idle / processing) |
| `gate clear` | Clear conversation history |
| `gate confirm on\|off` | Toggle confirmation for destructive commands |
| `gate restart` | Restart the AI backend session |
| *(anything else)* | Forwarded to the AI as a prompt |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "*`/cmd` is not a valid command*" error from Slack | Slack intercepts messages starting with `/` as slash commands | Use the `gate` prefix instead: `gate help`, `gate sync`. If you must type `/`, precede with a space: ` /cmd` |
| Bot visible in Apps but can't DM it | Messages Tab disabled | **App Home** → **Messages Tab** → enable "Allow users to send Slash commands and messages from the messages tab" |
| Can't invite bot to channel | Missing scope or not installed | Reinstall app (step 5) after adding scopes |
| `/invite @BotName` doesn't work | Use the channel's **Integrations** tab instead | Channel settings → **Integrations** → **Add apps** |
| `invalid_auth` in logs | Wrong or stale token | Reinstall app (step 5) and update `SLACK_BOT_TOKEN` |
| `not_in_channel` errors | Bot not in channel | Add via channel Integrations → Add apps |
| Ready message not sent | `SLACK_CHANNEL_ID` not set | Add channel ID to `.env` and restart |
| Streaming not working | `STREAM_RESPONSES=false` | Set `STREAM_RESPONSES=true` in `.env` |
| Events not received | Event Subscriptions not enabled | Complete step 4, then reinstall (step 5) |
