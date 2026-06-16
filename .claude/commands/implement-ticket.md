---
description: "Gate a ticket to 10/10, implement the delta, code-review it, and push to develop"
argument-hint: "<issue-number>"
---

Implement an AgentGate GitHub issue end-to-end: gate the ticket until it is implementation-ready,
build the change, review the diff, and ship it to `develop`.

## Usage

Accepted argument: `<issue-number>` (required)

Example: `/implement-ticket 44`

## Pipeline

Run these four stages in order. Do not skip ahead — each stage gates the next.

### Stage 1 — Gate to 10/10 (loop autonomously)

The gate scores the **GitHub issue's readiness**, not the code. Loop until it passes:

1. Use the Agent tool with `subagent_type: ticket-gate`, passing the issue number as the prompt.
2. If the result is **PASS** (all agents 10/10), continue to Stage 2.
3. If **BLOCKED**, address every required change by **editing the GitHub issue body**
   (`gh issue edit <NUMBER> --repo agigante80/AgentGate --body-file ...`) to incorporate the
   missing detail — acceptance criteria, security/redaction notes, architecture constraints, etc.
4. Re-run the gate. Keep iterating autonomously until it reaches 10/10. Do **not** stop to ask.

Only proceed once the gate returns PASS.

### Stage 2 — Implement the delta

Build the change described by the now-10/10 ticket, following repo conventions in `CLAUDE.md`:

- Use TDD (`superpowers:test-driven-development`) — failing test first, then implementation.
- Honor key conventions: redaction order, `scrubbed_env()`, `sanitize_git_ref()`, `REPO_DIR`/
  `DB_PATH`/`AUDIT_DB_PATH` constants, `secret_values()` on new sub-configs, command symmetry
  between `bot.py` and `slack.py`, registry registration.
- If a config/env var is added, update `.env.example`, `README.md`, and `docker-compose.yml.example`.

Verify before moving on:

```bash
ruff check src/
python scripts/lint_docs.py
pytest tests/ -v --tb=short
```

All three must be clean. Fix and re-run until they pass.

### Stage 3 — Code-review the diff (blocking)

Run `/code-review --fix` on the working diff (fast, focused — correctness bugs + cleanup).

- Apply the findings.
- Re-run `ruff check src/` and `pytest tests/` to confirm the fixes didn't regress anything.
- Treat unresolved blocking findings as a hard gate — do not push until they are resolved.

### Stage 4 — Push to develop

Direct commit + push to `develop` (no PR, no feature branch — this is the durable workflow):

```bash
git add -A
git commit   # Conventional Commit message referencing the issue, e.g. "feat: ... (#44)"
git push origin develop
```

Note: `develop` is **not** the default branch (`main` is), but pushing directly to `develop` is the
intended behavior here. No VERSION bump is required for `develop` (only `main` enforces it). The push
publishes the `:develop` Docker tag via CI.

## Report

When done, summarize: gate rounds taken to reach 10/10, what was implemented, code-review findings
applied, test/lint status, and the pushed commit SHA.
