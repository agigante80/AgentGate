# Remote Machine Control — Spin-off Project Brief

> **Status:** Concept / Pre-development  
> **Origin:** Derived from [AgentGate](https://github.com/agigante80/AgentGate) v0.7.3  
> **Author:** Initial concept captured 2026-03-10  

---

## 1. The Core Idea

AgentGate was built as a developer tool — a chatbot gateway that gives AI models access to a GitHub-cloned code repository, with shell execution, streaming responses, and persistent history. Along the way it became something else too: **a fully functional AI-augmented remote shell for any machine it runs on.**

This document proposes extracting and refocusing that power into a standalone project: **an easy-to-install, AI-enhanced remote control daemon for any machine — laptop, server, Raspberry Pi, VM, or cloud instance — accessible from Telegram or Slack without requiring open ports, VPNs, or firewall changes.**

The security implications are significant, intentional, and worth understanding deeply — both offensively and defensively.

---

## 2. Prompt for an AI Coding Agent

> You are building a new open-source project called [PROJECT NAME]. It is a **spin-off of AgentGate** (https://github.com/agigante80/AgentGate), a Telegram/Slack bot with shell execution and AI backends.
>
> **Goal:** Create a standalone Python application — installable with `pip install [package-name]` and startable with a single CLI command — that lets a user remotely control any machine (laptop, server, Raspberry Pi, cloud VM) from Telegram or Slack. The user can run shell commands, ask AI questions about the machine state, and receive streaming responses, all authenticated by Telegram chat ID / Slack user ID.
>
> **Source of truth:** Fork or cherry-pick from AgentGate. The following modules are portable with little or no change:
> - `src/ai/` — all AI backends (copilot, codex, direct API)
> - `src/platform/` — Telegram bot handlers and Slack bot
> - `src/history.py` — SQLite conversation history
> - `src/executor.py` — shell runner (change `cwd` from `/repo` to configurable `WORK_DIR`)
> - `src/transcriber.py` — voice-to-text
> - `src/logging_setup.py` — logging
>
> **Remove entirely:**
> - `src/repo.py` — no GitHub repo cloning
> - `src/runtime.py` — no dependency auto-install
> - `GitHubConfig` section of `src/config.py`
> - `cmd_sync`, `cmd_git`, `cmd_diff`, `cmd_log` bot commands (git-specific)
>
> **Add/change:**
> - `WORK_DIR` env var (default: `$HOME`) replaces `REPO_DIR`
> - `CWD` state tracking per chat session: `gate cd <path>` changes the working directory for subsequent `gate run` calls
> - Persistent CWD across restarts (store in SQLite alongside history)
> - Shell audit log (every command run, timestamp, exit code, chat_id) written to `DATA_DIR/audit.log`
> - System snapshot command: `gate snap` — runs `uptime`, `df -h`, `free -h`, `ip a` and returns a summary
> - Process monitor: `gate ps [pattern]` — lists matching processes with AI summarisation if list is long
> - `gate whoami` — returns hostname, OS, current user, uptime, IP addresses
> - Installation: `pyproject.toml` with `[project.scripts] remote-gate = "remote_gate.main:main"`
> - Docker support: minimal `Dockerfile` and `docker-compose.yml.example`
> - First-run wizard: if no env file exists, `remote-gate init` walks the user through creating `.env` interactively
> - Health check endpoint (optional HTTP GET `/health`) for uptime monitoring
> - README with one-command install, security warnings, and red team / blue team awareness section
>
> **Security requirements:**
> - Auth by Telegram `CHAT_ID` + optional `ALLOWED_USERS` allowlist (identical to AgentGate)
> - All destructive commands require inline confirmation (identical pattern)
> - `COMMAND_ALLOWLIST` env var: if set, only whitelisted command prefixes are permitted
> - `COMMAND_BLOCKLIST` env var: always-blocked patterns (e.g. `rm -rf /`, `mkfs`)
> - Audit log is append-only; no API to delete it remotely
> - README must include a section on responsible use, risks, and threat model
>
> **Non-goals (keep it simple):**
> - No web UI
> - No multi-machine orchestration (that is a v2 problem)
> - No file upload/download (v2)
> - No SSH tunnelling or port forwarding
>
> Produce: repo scaffold, `pyproject.toml`, `src/` layout, `Dockerfile`, `docker-compose.yml.example`, `.env.example`, `README.md`.

---

## 3. Project Name Candidates

### Option A — **RemoteGate**

| Pros | Cons |
|------|------|
| Directly communicates purpose | Generic; likely taken on PyPI |
| Shares "Gate" suffix with AgentGate — brand family | No security connotation |
| Easy to remember and spell | Could imply network gateway (VPN/firewall) |
| `pip install remotegate` reads naturally | Not distinctive enough to stand out |

---

### Option B — **ShellHand**

| Pros | Cons |
|------|------|
| Evocative of "remote hand" on a server | Less obviously AI-related |
| Unusual enough to be memorable and available on PyPI | "Hand" metaphor is vague |
| Works as a verb: "shellhand into my pi" | Slightly playful — may not suit enterprise |
| Security community would appreciate the dual meaning | No "AI" signal in the name |

---

### Option C — **GhostShell**

| Pros | Cons |
|------|------|
| Strong red team / security connotation | Could attract wrong associations (malware naming) |
| Memorable; sounds powerful | May cause friction in enterprise/compliance contexts |
| Name is evocative of stealth / remote presence | Likely conflicts with existing tools / CTF references |
| Immediately interesting to security researchers | GitHub/PyPI availability uncertain |

---

### Option D — **Heimdall**

| Pros | Cons |
|------|------|
| Norse mythology: the watchman of Bifrost (a bridge/gateway) | Already used by several projects (dashboards, auth) |
| Perfect metaphor: stands watch, controls access, sees everything | Requires disambiguation |
| Memorable, distinctive, culturally recognised | May seem over-branded for a CLI daemon |
| Strong connotation of controlled access and vigilance | Non-obvious what it does without context |

---

### Option E — **PresenceD** *(presence daemon)*

| Pros | Cons |
|------|------|
| Honest about what it is: a persistent background daemon | The "D" suffix reads like sysd naming — niche |
| "Presence" captures remote awareness without implying shell | Technical audience only |
| Unique; almost certainly available on PyPI | Not memorable outside sysadmin circles |
| Has a defensive, monitoring connotation | Undersells the AI and shell power |

---

### Recommendation

**ShellHand** for open-source community appeal and availability. **GhostShell** if the project leans explicitly into the red team angle. Avoid **Heimdall** due to naming conflicts.

---

## 4. Repository Structure

```
[project-name]/
├── .github/
│   ├── copilot-instructions.md
│   └── workflows/
│       ├── ci.yml              # lint + test
│       └── release.yml         # PyPI publish + Docker push
├── docs/
│   ├── quickstart.md
│   ├── security.md             # threat model, red/blue team analysis
│   └── configuration.md
├── src/
│   └── [package_name]/
│       ├── __init__.py
│       ├── main.py             # entrypoint, startup, signal handling
│       ├── config.py           # Pydantic settings (no GitHubConfig)
│       ├── executor.py         # run_shell(), cwd tracking, audit log
│       ├── history.py          # SQLite conversation + cwd state
│       ├── session.py          # per-chat session state (cwd, mode)
│       ├── logging_setup.py
│       ├── ready_msg.py
│       ├── transcriber.py
│       ├── wizard.py           # `init` first-run interactive setup
│       ├── health.py           # optional HTTP /health endpoint
│       ├── ai/
│       │   ├── adapter.py
│       │   ├── factory.py
│       │   ├── copilot.py
│       │   ├── codex.py
│       │   ├── direct.py
│       │   └── session.py
│       └── platform/
│           ├── common.py
│           ├── telegram.py     # renamed from bot.py
│           └── slack.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── Dockerfile
├── docker-compose.yml.example
├── .env.example
├── pyproject.toml
├── VERSION
└── README.md
```

---

## 5. Configuration Delta vs AgentGate

### Removed env vars:
```
GITHUB_REPO_TOKEN
GITHUB_REPO
GITHUB_BRANCH
```

### Added env vars:
```bash
WORK_DIR=/home/user          # Default working directory for shell commands (default: $HOME)
DATA_DIR=/data               # SQLite, audit log, sentinels (default: ~/.local/share/[project])
COMMAND_ALLOWLIST=           # Comma-separated allowed command prefixes. Empty = allow all.
COMMAND_BLOCKLIST=rm -rf /,mkfs  # Always-blocked patterns regardless of confirmation.
AUDIT_LOG_ENABLED=true       # Write audit.log for every executed command.
HEALTH_PORT=0                # Set >0 to enable HTTP health endpoint on that port.
```

### Kept unchanged:
```bash
TG_BOT_TOKEN, TG_CHAT_ID, ALLOWED_USERS
SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID, SLACK_ALLOWED_USERS
AI_CLI, AI_API_KEY, AI_MODEL, AI_PROVIDER, AI_BASE_URL
WHISPER_PROVIDER, WHISPER_API_KEY, WHISPER_MODEL
PLATFORM, LOG_LEVEL, LOG_DIR
BOT_CMD_PREFIX, MAX_OUTPUT_CHARS, STREAM_RESPONSES, STREAM_THROTTLE_SECS
CONFIRM_DESTRUCTIVE, SKIP_CONFIRM_KEYWORDS
```

---

## 6. Bot Command Changes vs AgentGate

### Removed (git/repo-specific):
| Command | Reason |
|---------|---------|
| `gate sync` | Pulls GitHub repo — not applicable |
| `gate git <args>` | Raw git passthrough — not applicable |
| `gate diff` | Shows git diff — not applicable |
| `gate log` | Shows git log — not applicable |
| `gate install` | Re-runs dep installer — not applicable |

### Added (machine-specific):
| Command | Description |
|---------|-------------|
| `gate cd <path>` | Change working directory for this session (persisted) |
| `gate pwd` | Show current working directory |
| `gate snap` | Snapshot: uptime + disk + memory + network |
| `gate ps [pattern]` | List processes matching pattern |
| `gate whoami` | Hostname, OS, user, uptime, IPs |
| `gate watch <cmd> <secs>` | Run command every N seconds, stream updates |
| `gate env [key]` | Show env vars (filtered; never shows secrets) |

### Unchanged:
`gate run`, `gate help`, `gate clear`, `gate restart`, `gate status`, `gate confirm`, `gate ta` (text-from-audio)

---

## 7. Use Cases

### Personal & Professional:

1. **Headless home lab management.** Raspberry Pi running in a closet. No monitor, no keyboard. Telegram on your phone → `gate run systemctl status pihole` → AI interprets and summarises. No SSH client needed.

2. **Remote dev machine while travelling.** Your powerful workstation is at home. You're on a train with only a phone. Ask AI to make a code change, run tests, tail a log — all via Telegram.

3. **"Is it down?" first response.** Woken up at 3am. Server alert fires. Before opening a laptop, ask the bot: "Is the web server OK?" — `gate snap` + AI analysis before you've even unlocked your computer.

4. **IoT / embedded device monitoring.** Small Python footprint. Runs on any device with an internet connection. Replace bespoke monitoring dashboards with a chat interface.

5. **Air-gapped machine reach-back.** Machine has outbound internet but no inbound. Traditional SSH fails. This works via Telegram's outbound HTTPS connection.

### Scenarios where you'd want this installed:

| Machine | Why |
|---------|-----|
| Home server / NAS | Admin from anywhere, no port forwarding |
| Raspberry Pi (home automation, media server) | Headless control from phone |
| Developer workstation | Remote coding assistant when away |
| Cloud VMs without bastion | Reach a VM in a VPC with no inbound rules |
| CI/CD runner (self-hosted) | Trigger jobs, inspect state |
| Company laptop (personal/BYOD) | Remote access without VPN (with appropriate policy) |

---

## 8. Why Not Just Use SSH?

This is the right question to ask. The honest answer is: **SSH is better for power users who control their infrastructure.** This tool is better for everyone else — and for certain security scenarios.

### SSH advantages over this tool:
- Full terminal emulator (ncurses, vim, htop work perfectly)
- No third-party service in the path (no Telegram)
- Standard protocol with mature tooling (keys, agents, multiplexing)
- File transfer (scp/sftp)
- Port forwarding / tunnelling

### Where this tool wins:

| Scenario | SSH | This tool |
|----------|-----|-----------|
| Inbound port blocked by NAT/firewall | ❌ Needs port forward | ✅ Outbound HTTPS only |
| Machine behind CGNAT (4G home router) | ❌ No public IP | ✅ Works |
| No SSH client on the device (phone, tablet) | ❌ Needs app | ✅ Native Telegram |
| AI-augmented responses | ❌ Raw shell only | ✅ AI interprets and explains |
| Confirmation UX for dangerous commands | ❌ Nothing stops you | ✅ Inline button approval |
| Non-technical users | ❌ Steep learning curve | ✅ Natural language |
| Voice commands | ❌ Not applicable | ✅ Voice → shell (Whisper) |
| Conversation history / context | ❌ Stateless | ✅ 10-exchange context window |

### What about Telegram-based shell bots (e.g. Botgram, Shell-Bot)?

They exist and work. The gap is: they're **raw shell relays** with no AI. You still need to know exactly what command to run. This project adds the AI reasoning layer — you can ask "why is disk 90% full?" and get an answer, not just output.

---

## 9. Red Team / Blue Team Analysis

> **Important disclosure:** This tool, by design, provides remote shell access to any machine it runs on. Like SSH, Metasploit, netcat, or a VPN, it is a dual-use technology. Understanding it from both offensive and defensive perspectives is the responsible way to build and deploy it.

### 🔴 Red Team Perspective: Why This Is a Compelling Implant Model

Security researchers and red teamers will immediately recognise what this architecture resembles: **a C2 (Command and Control) beacon using a legitimate third-party channel.**

| Property | AgentGate / spin-off | Classic C2 implant |
|----------|---------------------|-------------------|
| Outbound-only traffic | ✅ HTTPS to Telegram API | ✅ Often beacons home via HTTPS |
| Uses legitimate domain | ✅ `api.telegram.org` | ✅ Often uses CDNs, Slack, Discord |
| No inbound ports | ✅ | ✅ |
| Bypasses many firewall policies | ✅ | ✅ |
| Encrypted transport | ✅ TLS | ✅ TLS |
| Authenticated C2 channel | ✅ Telegram bot token | ✅ Implant UUID / beacon key |
| Persistence across reboots | Needs systemd unit | Needs persistence mechanism |
| Operator UX | Telegram app | Cobalt Strike / Mythic / custom |

**Key insight for red teamers:** Telegram-based C2 is a real, documented technique (see: [TeleRAT](https://unit42.paloaltonetworks.com/unit42-telerat-another-android-trojan-leveraging-telegrams-bot-api-to-target-iranian-users/), [Masad Stealer](https://www.zscaler.com/blogs/security-research/masad-stealer-exfiltrating-using-telegram), multiple APT campaigns). This project is the **legitimate, open, user-consented version** of that pattern.

**What makes this detectable / distinguishable from a real implant:**
- Installed openly, not via exploit or dropper
- Runs as a known process with a clear process name
- Source code is public
- Auth requires the Telegram account of the machine owner

**Red team scenarios this enables (with consent):**
- Persistent access to a lab environment without maintaining an SSH tunnel
- Quick-reaction capability from a mobile device during an engagement (where your laptop may not be available)
- AI-assisted lateral movement research in an isolated lab

---

### 🔵 Blue Team Perspective: Detection and Defence

**If you find this tool on a machine you didn't install it on — treat it as a serious incident.**

#### Detection indicators:

| Indicator | What to look for |
|-----------|-----------------|
| Network | Regular outbound HTTPS connections to `api.telegram.org` (149.154.x.x / 91.108.x.x) |
| Process | Python process named `remote-gate`, `agentgate`, or with `main.py` in args |
| Files | `.env` file with `TG_BOT_TOKEN`, `history.db`, `audit.log` in home or data dir |
| Systemd | `remote-gate.service` or similar unit file |
| Cron | Cron entry restarting a Python bot script |
| Docker | Container exposing no ports but making outbound Telegram connections |

#### Defensive controls:

1. **Network egress filtering.** Block outbound connections to `api.telegram.org` and `slack.com` on managed endpoints if Telegram/Slack are not approved apps.

2. **Process allowlisting.** Endpoint solutions (CrowdStrike, Carbon Black) can alert on unexpected Python processes with `asyncio` / `telegram` libraries making network calls.

3. **Audit log review.** If the tool *is* legitimately installed, periodically review `DATA_DIR/audit.log`. Any unexpected commands are an indicator of account compromise.

4. **Telegram bot token hygiene.** Bot tokens are long-lived and do not expire unless revoked. If a `TG_BOT_TOKEN` is leaked (e.g., in a public `.env` commit), revoke it immediately via `@BotFather → /revoke`.

5. **ALLOWED_USERS enforcement.** Always set `ALLOWED_USERS` to your specific Telegram user ID. The default (`CHAT_ID` only) is weaker — if someone else gets your bot token, they can't send to your chat, but defence in depth is better.

6. **Principle of least privilege.** Run the daemon as a dedicated user with minimal permissions, not as root.

#### Awareness for blue teamers:

- Telegram-based C2 is increasingly common in nation-state and commodity malware. **Train your SOC to recognise `api.telegram.org` in egress traffic as a potential indicator, not just a productivity tool.**
- This project's open publication is itself a defensive act: by documenting the pattern, defenders can build detections before adversaries do (or further weaponise it).

---

## 10. Implementation Complexity Estimate

| Component | Effort | Notes |
|-----------|--------|-------|
| Fork & strip repo-specific code | 1-2 hours | Remove 3 modules, adjust imports |
| CWD tracking (executor + SQLite) | 2-3 hours | New column in history DB, session state |
| Audit log | 1 hour | Append-only file writer in `executor.py` |
| New machine commands (snap, ps, whoami) | 2 hours | Thin wrappers around existing `run_shell` |
| pyproject.toml + CLI entrypoint | 1 hour | Replace Dockerfile-only startup |
| First-run wizard (`init` command) | 2-3 hours | Interactive env file generator |
| COMMAND_ALLOWLIST / BLOCKLIST | 1-2 hours | Extend `executor.py` checks |
| Health endpoint | 1 hour | Simple asyncio HTTP server |
| README + docs | 3-4 hours | Worth doing properly given security sensitivity |
| Tests | 3-4 hours | Port existing tests, add CWD and audit tests |
| **Total estimate** | **~18-22 hours** | Solo developer, familiar with AgentGate |

---

## 11. Open Questions / Decisions Before Starting

1. **Package name:** Which of the 5 names? Check PyPI availability before committing.
2. **Shared library approach?** Extract `agentgate-core` (AI backends + platform layer) as a shared dependency, or keep as a standalone fork?
3. **Multi-machine support (v2)?** A single bot token → multiple machines (each a separate "room") is a natural extension. Design the DB schema to support it from day one?
4. **File transfer?** `gate upload` / `gate download` via Telegram's file API is high-value but increases attack surface.
5. **Audit log format:** Plain text vs structured JSON (for log shippers like Filebeat)?
6. **Responsible disclosure:** Consider a security policy file and coordinating with Telegram if any vulnerability in the bot pattern is found.

---

## 12. Related Art / Prior Work

| Project | URL | Relationship |
|---------|-----|--------------|
| Botgram | https://github.com/nicowillis/botgram | Telegram shell relay, no AI |
| tg-commander | Various | Telegram shell, limited auth |
| TeleRAT | (malware) | Same outbound-C2 pattern, malicious context |
| Mythic C2 | https://github.com/its-a-feature/Mythic | Full C2 framework with similar comms concepts |
| ShellGPT | https://github.com/TheR1D/shell_gpt | AI shell assistant, local only |
| AgentGate | https://github.com/agigante80/AgentGate | **Parent project** |

---

*Document generated: 2026-03-10. This is a planning document, not production code. All security analysis is provided for educational and defensive awareness purposes.*
