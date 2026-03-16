# AgentGate — Roadmap

> Last updated: 2026-03-15 (roadmap-sync: removed 3 implemented features — docs-align-sync, request-cancellation, thinking-persist)

A lean, prioritized list of work for AgentGate. Each item is a short name, one-line description, and a link to a feature document under `docs/features/`.

If adding a new item, create a feature document using `docs/features/_template.md` before implementation; the template ensures consistent scope, tests, and versioning guidance.

---

## Technical Debt

| # | Item | Detail |
|---|------|--------|

---

## Features

| # | Item | Detail |
|---|------|--------|
| 2.1 | Improved security scanning — complete Trivy + add CodeQL SAST and pip-audit dependency scan | [→ features/improved-security-scanning.md](features/improved-security-scanning.md) |
| 2.2 | Modular plugin architecture — registry-based subsystems for fork cherry-picking (pre-work for forks) | [→ features/modular-plugin-architecture.md](features/modular-plugin-architecture.md) |
| 2.3 | Copilot session pre-warming — reduce repeated context setup overhead | [→ features/copilot-prewarm.md](features/copilot-prewarm.md) |
| 2.4 | Token/cost tracking — capture OpenAI usage payloads, surface spend via `/gate status` | [→ features/token-cost-tracking.md](features/token-cost-tracking.md) |
| 2.5 | `/gate schedule` — recurring shell commands or AI prompts | [→ features/schedule.md](features/schedule.md) |
| 2.6 | Gemini CLI backend — `AI_CLI=gemini` (Google Gemini CLI) | [→ features/gemini-cli-backend.md](features/gemini-cli-backend.md) |
| 2.7 | `/gate switch` — hot-swap the AI backend at runtime | [→ features/switch-backend.md](features/switch-backend.md) |
| 2.8 | Proactive alerts — notify chat on file changes or log keyword matches | [→ features/proactive-alerts.md](features/proactive-alerts.md) |
| 2.9 | Multi-provider git hosting — GitLab, Bitbucket, Azure DevOps (`REPO_PROVIDER`) | [→ features/multi-provider-git-hosting.md](features/multi-provider-git-hosting.md) |
| 2.10 | `/gate file` — send/receive files to/from `/repo` via chat | [→ features/file-transfer.md](features/file-transfer.md) |
| 2.11 | Voice transcription — local Whisper provider | [→ features/whisper-local.md](features/whisper-local.md) |
| 2.12 | Voice transcription — Google Speech-to-Text provider | [→ features/whisper-google.md](features/whisper-google.md) |
| 2.13 | Lightweight web dashboard — read-only HTTP status page in the container | [→ features/web-dashboard.md](features/web-dashboard.md) |
| 2.14 | Prometheus metrics endpoint — expose request/error/latency metrics via `/metrics` | [→ features/metrics-endpoint.md](features/metrics-endpoint.md) |
| 2.15 | Remote control fork project — `gate fork` subcommands for cross-repo cherry-pick workflows | [→ features/remote-control-fork-project.md](features/remote-control-fork-project.md) |
| 2.16 | Supply-chain hardening — `detect-secrets` CI gate + dependency pinning | [→ features/supply-chain-hardening.md](features/supply-chain-hardening.md) |
| 2.17 | ✅ API key scheme refactor — explicit per-backend keys; remove `AI_API_KEY` master fallback | [→ features/api-key-scheme.md](features/api-key-scheme.md) |
| 2.18 | `AI_PROVIDER` explicit validation — require `AI_PROVIDER` to be non-empty when `AI_CLI=api`; raise clear `ValueError` at startup | _(spec TBD)_ |

---

*Implemented items have been removed from this list. Each roadmap entry must have a corresponding feature document under `docs/features/`. If a linked file is missing, create it from `docs/features/_template.md` before starting implementation.*
