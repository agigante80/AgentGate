---
description: "Run the ticket readiness gate on an AgentGate GitHub issue before implementation"
argument-hint: "<issue-number>"
---

Run the ticket readiness gate on a GitHub issue.

## Usage

Accepted argument: `<issue-number>` (required)

Example: `/gate-ticket 44`

## Steps

Use the Agent tool with `subagent_type: ticket-gate`, passing the issue number as the prompt.

The ticket-gate agent handles all steps:
1. Template version check — auto-synthesises missing sections if no version marker is present (no BLOCK)
2. Fetches the issue from `agigante80/AgentGate`
3. Reads project context: `CLAUDE.md`, `src/config.py`, `src/ai/adapter.py`, `src/executor.py`, `src/redact.py`
4. Runs 5 core agents (Security, Architect, Developer, QA, GDPR) + dynamic agents selected by
   `type:*`/`area:*` labels and body content, sequentially
5. Compiles and posts the scorecard as a GitHub comment
6. Returns PASS or BLOCKED with specific required changes

AgentGate-specific scoring: the Security agent checks redaction order, `scrubbed_env()` usage,
`sanitize_git_ref()`, SQL parameterization, and `ALLOW_SECRETS` flag. The Architect agent
checks CLAUDE.md conventions: `REPO_DIR`/`DB_PATH` constants, `secret_values()`, command
symmetry between `bot.py` and `slack.py`, and registry registration.

All agents must score 10/10 for the ticket to be considered implementation-ready.
