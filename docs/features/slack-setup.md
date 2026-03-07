# Slack Setup Guide

> Platform: **Slack** (`PLATFORM=slack`)  
> Connection: Socket Mode (WebSocket — no public endpoint required)

This guide walks through creating a Slack App, configuring the required scopes and events, obtaining the tokens, and wiring them into TeleAgent.

---

## 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Give it a name (e.g. `taVPNSentinel`) and pick your workspace
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

In the left sidebar: **Settings** → **Socket Mode**:

1. Toggle **Enable Socket Mode** → **ON**
2. A dialog appears — give the token a name (e.g. `socket-token`)
3. Click **Add Scope** → select `connections:write`
4. Click **Generate**
5. Copy the token — it starts with `xapp-` → this is your **`SLACK_APP_TOKEN`**

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
2. Type `/invite @YourBotName` and press Enter
3. To get the **Channel ID**: right-click the channel name → **Copy link** — the ID is the last segment of the URL (e.g. `C08XXXXXXXX`) → this is your **`SLACK_CHANNEL_ID`** (optional but recommended)

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
> TeleAgent does NOT use slash commands. Always use the plain-text `ta` prefix instead.  
> `ta help` ✅ — `/help` ❌ (Slack will reject it as an unknown slash command)  
> If you accidentally type `/cmd`, precede it with a space (` /cmd`) to send it as text — but it's better to just use `ta`.

Commands use the configurable prefix (`BOT_CMD_PREFIX`, default `ta`) as plain-text messages — no slash command registration required:

| Message | Action |
|---|---|
| `ta help` | Show available commands |
| `ta sync` | Pull latest changes from the repo |
| `ta run <cmd>` | Run a shell command in the repo directory |
| `ta git <args>` | Run a git command |
| `ta diff` | Show current git diff |
| `ta log` | Show recent git log |
| `ta status` | Show bot status (idle / processing) |
| `ta clear` | Clear conversation history |
| `ta confirm on\|off` | Toggle confirmation for destructive commands |
| `ta restart` | Restart the AI backend session |
| *(anything else)* | Forwarded to the AI as a prompt |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "*`/cmd` is not a valid command*" error from Slack | Slack intercepts messages starting with `/` as slash commands | Use the `ta` prefix instead: `ta help`, `ta sync`. If you must type `/`, precede with a space: ` /cmd` |
| Bot visible in Apps but can't DM it | Messages Tab disabled | **App Home** → **Messages Tab** → enable "Allow users to send Slash commands and messages from the messages tab" |
| Can't invite bot to channel | Missing scope or not installed | Reinstall app (step 5) after adding scopes |
| `/invite @BotName` doesn't work | Use the channel's **Integrations** tab instead | Channel settings → **Integrations** → **Add apps** |
| `invalid_auth` in logs | Wrong or stale token | Reinstall app (step 5) and update `SLACK_BOT_TOKEN` |
| `not_in_channel` errors | Bot not in channel | Add via channel Integrations → Add apps |
| Ready message not sent | `SLACK_CHANNEL_ID` not set | Add channel ID to `.env` and restart |
| Streaming not working | `STREAM_RESPONSES=false` | Set `STREAM_RESPONSES=true` in `.env` |
| Events not received | Event Subscriptions not enabled | Complete step 4, then reinstall (step 5) |
