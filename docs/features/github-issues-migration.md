# GitHub Issue Migration for Feature Tracking

> Status: **In Progress (Phase 1 implemented on `develop`)** | Priority: High | Last reviewed: 2026-03-18

This feature outlines the phased plan to convert existing feature documents in `docs/features/` into GitHub issues for streamlined prioritization and tracking. It also defines mixed-mode operation during migration, with legacy docs cleanup and full automation deferred to follow-up work.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/github-issues-migration.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 8/10 | 2026-03-17 | Good direction; narrowed to phased migration and repo-accurate config/tooling details. |
| GateSec  | 1 | 8/10 | 2026-03-17 | Phase 1 surface clean; added threat model, fixed align-sync scoping, tightened Phase 2 security reqs. |
| GateDocs | 1 | 9/10 | 2026-03-17 | The document is well-structured and comprehensive, providing a clear plan for the migration and new review process. |
| GateCode | 2 | 9/10 | 2026-03-17 | Tightened phase boundaries, corrected version/scope inconsistencies, and made migration outputs/acceptance criteria fully testable. |
| GateSec  | 2 | 9/10 | 2026-03-17 | Round 2 clean; added export-dir gitignore req, adversarial-input test case, parity-report trust guidance, and external-contributor security answer. |
| GateDocs | 2 | 9/10 | 2026-03-17 | Final review confirms document clarity, completeness, and alignment with project goals. |

**Status**: ✅ Approved
**Approved**: Yes — all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1.  **Scope** — Internal process change affecting docs workflow and agent operating instructions; platform-agnostic.
2.  **Backend** — No new AI backend. Existing CLIs may optionally invoke `gh` in a later phase.
3.  **Stateful vs stateless** — N/A.
4.  **Breaking change?** — For migration phase, treat as non-breaking (`MINOR`) because docs remain available during transition. Re-assess if/when destructive cleanup lands.
5.  **New dependency?** — No dependency needed for phase 1 (manual issue creation). Future automation should prefer the existing `gh` CLI audited path before introducing new SDK dependencies.
6.  **Persistence** — No runtime persistence changes.
7.  **Auth** — Reuse existing `GitHubConfig.github_repo_token` (`GITHUB_REPO_TOKEN`) for future automation; do not introduce duplicate token env vars.
8.  **Automated GitHub Interaction** — Feasible in a follow-up phase once a least-privilege token model and auditable command path are defined.

---

## Problem Statement

1.  **Manual Synchronization**: The current `docs/features/` and `docs/roadmap.md` system requires manual updates, leading to inconsistencies and stale information.
2.  **Lack of Integrated Prioritization**: Features are not prioritized within a dynamic system, making it difficult to re-prioritize and track progress effectively.
3.  **Inefficient Review Process**: The current feature review process is document-centric, requiring manual delegation and status updates, which is not scalable or easily auditable.
4.  **Limited Automation**: The existing `docs roadmap-sync` command only addresses feature-status bookkeeping and is not integrated with project management tools. (`docs align-sync` handles README/config/env synchronization and is out of scope for this migration.)
5.  **Disparate Systems**: Feature planning, tracking, and development are spread across different systems (documentation, code, chat), leading to overhead and potential miscommunication.

---

## Current Behaviour (as of v1.2.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Docs | `docs/features/*.md` | Individual feature specifications, manually updated. |
| Docs | `docs/roadmap.md` | Centralized list of features and their status, manually updated. |
| Commands | `docs roadmap-sync` | Synchronizes `docs/features/` and `docs/roadmap.md`, intended to keep them aligned but requires manual trigger and doesn't fully automate. |
| Commands | `docs align-sync` | Synchronizes `README.md`, `.env.example`, `docker-compose.yml.example`, and `src/config.py`. Out of scope — retained after migration. |
| Guides | `docs/guides/feature-review-process.md` | Defines a manual, document-centric review process involving GateCode, GateSec, and GateDocs. |
| Template | `docs/features/_template.md` | Template for new feature documents. |

> **Key gap**: The current system relies heavily on manual intervention for feature tracking, prioritization, and review, leading to inefficiencies and a lack of real-time visibility into project status. There is no automated, integrated workflow with GitHub for feature management.

---

## Design Space

### Axis 1 — Automated GitHub Issue Creation

#### Option A — Manual creation from generated Markdown *(status quo / baseline for now)*

A script generates Markdown files from `docs/features/`, and users manually copy/paste to create GitHub issues.

**Pros:**
- Low technical overhead for agents (no GitHub API access needed initially).
- Provides a clear migration path.

**Cons:**
- Not fully automated; still requires human intervention.
- Prone to human error in copying/pasting.

---

#### Option B — Direct GitHub API interaction by agents *(recommended future state)*

Agents use dedicated tools or libraries to interact directly with the GitHub API for issue creation, updates, and management.

**Pros:**
- Fully automated workflow.
- Reduces human error and overhead.
- Enables real-time updates and integration with GitHub features (labels, assignees, comments).

**Cons:**
- Requires agents to have secure and persistent GitHub API access, which is a current limitation.
- Requires development of new tools or wrappers for existing GitHub APIs.

**Recommendation: Option A for initial migration, with a clear roadmap to Option B.** — This allows for incremental progress while addressing the immediate need for migration and setting the stage for full automation.

---

### Axis 2 — New Feature Review Process

#### Option A — Current document-centric review *(status quo)*

Reviews are conducted by editing feature documents directly, with scores and notes appended to the document.

**Pros:**
- Familiar process to the team.

**Cons:**
- Not integrated with GitHub's native issue management.
- Difficult to track review progress and discussions within GitHub.
- Requires manual status updates in the document.

---

#### Option B — GitHub-issue-centric review *(recommended)*

Reviews are conducted directly on GitHub issues. Reviewer scores, notes, and delegation are handled through comments, labels for status (e.g., `review: pending`, `review: approved`), and assignees for delegation.

**Pros:**
- Leverages GitHub's native features for discussion, tracking, and status management.
- Enables automation of review states and notifications.
- Consolidates all feature-related discussions in one place.
- Compatible with existing `DELEGATE` protocol for agents.

**Cons:**
- Requires adaptation from the current document-based workflow.
- Initial setup and agent tool development for full automation.

**Recommendation: Option B** — This provides a more robust, auditable, and automatable review process that aligns with modern development workflows.

---

## Recommended Solution

Deliver this in two explicit phases to avoid a risky all-at-once cutover.

-   **Phase 1 (this feature)**: Introduce issue templates and a deterministic export script that converts `docs/features/*.md` into GitHub-issue-ready Markdown for manual posting.
-   **Phase 1 process updates**: Keep the current review chain, but make the issue body the canonical source for new work while docs remain as migration source material.
-   **Phase 2 (follow-up feature)**: Add agent-driven GitHub issue CRUD using least-privilege auth and auditable command execution.
-   **Deferred cleanup**: Only remove `docs/roadmap.md` and legacy feature docs after a verified migration report confirms parity.

### Non-Goals (Phase 1)

-   No direct GitHub API/CLI mutation by agents (manual issue posting remains required).
-   No changes to runtime bot command routing/execution paths.
-   No deletion of legacy docs or roadmap file during the migration PR.

---

## Architecture Notes

-   **Agent GitHub Interaction**: For automation, prefer a single audited execution path (`gh` CLI with explicit allowlisted subcommands) over ad-hoc API wrappers spread across backends. All `gh` invocations must go through `run_shell()` so they are subject to `SHELL_ALLOWLIST`, audit logging, `SecretRedactor`, and destructive-command confirmation.
-   **Argument Sanitization**: Issue titles and body content originate from feature docs (semi-trusted) or user input (untrusted). Before interpolating into `gh` arguments, sanitize with `shlex.quote()` or pass via `--body-file` (stdin/tempfile) to avoid shell metacharacter injection. Never construct `gh` command strings via f-string interpolation of user content.
-   **Credential Reuse**: Use existing `Settings.github.github_repo_token`; avoid introducing `GITHUB_API_TOKEN` alongside it.
-   **Template Consistency**: Migration output must preserve acceptance criteria, open questions, and security notes from source docs.
-   **Backward Compatibility**: During phase 1, legacy docs remain readable to avoid disrupting active planning. `docs align-sync` is retained (it handles README/config sync, not feature tracking).
-   **Scalability**: Label taxonomy (`type:*`, `priority:*`, `review:*`) should support automation and board filtering.

---

## Security Considerations (Phase 2 Threat Model)

Phase 1 has minimal security surface (manual copy-paste, no API interaction, no new secrets). The threats below apply to Phase 2 automated GitHub interaction and must be addressed in that follow-up feature doc before implementation.

| Threat | Impact | Mitigation |
|--------|--------|------------|
| *Command injection via `gh` arguments* | Attacker-controlled issue title/body could inject shell metacharacters into `gh issue create` | Route all `gh` calls through `run_shell()`. Pass body content via `--body-file` (not inline args). Sanitize titles with `shlex.quote()`. |
| *Token scope creep* | `GITHUB_REPO_TOKEN` with full `repo` scope allows code pushes, branch deletion, secret access | Require least-privilege scope: `issues:write` + `metadata:read` only. Document required scopes in `.env.example`. |
| *Markdown injection in issue body* | Feature doc content copied into issue body could contain XSS payloads rendered by GitHub | Low risk — GitHub sanitizes rendered markdown. No additional mitigation needed. |
| *Audit trail gap* | `gh` commands bypassing `run_shell()` would skip audit log and `SecretRedactor` | Enforce that all `gh` invocations go through `run_shell()` with `redactor` param. Never call `subprocess` directly. |
| *Feature doc as prompt injection vector* | Migration script reads `docs/features/*.md` — a crafted doc could embed instructions | Script performs deterministic text extraction only, not LLM processing. Manual review of output before posting provides a human checkpoint. |
| *Token leakage in error messages* | `gh` CLI may echo the token in verbose/debug error output | `GITHUB_REPO_TOKEN` is already in `_SECRET_ENV_KEYS` (scrubbed from env) and `secret_values()` (redacted from output). Ensure `gh` receives token via `--with-token` stdin, not env var, to avoid accidental logging. |

---

## Config Variables

Initially, no new configuration variables are required for phase 1. For phase 2 automation, reuse the existing token variable already modeled in `GitHubConfig`.

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `GITHUB_REPO_TOKEN` | `str` | `""` | Existing repository token used by git/gh operations and future issue automation. |

---

## Implementation Steps

### Step 1 — Create GitHub Issue Templates

Create `.github/ISSUE_TEMPLATE/feature.md` for migrated feature specs.

-   Keep scope to the feature template required for this migration.
-   Optional bug/improvement templates can be tracked in a separate docs feature to avoid scope creep.

### Step 2 — Develop Feature Document Migration Script

Create a Python script (e.g., `scripts/migrate_features.py`) that:
-   Parses existing `docs/features/*.md` files.
-   Extracts key information (title, overview, problem statement, design, env vars, files to change, etc.).
-   Generates Markdown content formatted according to the new `feature.md` GitHub issue template.
-   Outputs generated Markdown files to `tmp/feature-issue-export/` for user review and manual GitHub issue creation.
-   Writes a deterministic parity manifest (`tmp/feature-issue-export/parity-report.json`) mapping each source doc to exported issue metadata (title, slug, labels) plus `source_sha256`/`output_sha256` hashes for integrity verification.
-   The `tmp/` directory must be `.gitignored` to prevent accidental commit of export artifacts (feature docs may contain example credentials or security notes not intended for issue tracker publication).

### Step 3 — Update Feature Review Process Guide

Revise `docs/guides/feature-review-process.md` to:
-   Define mixed-mode operation during migration: feature docs remain the review source-of-truth, with GitHub issues as tracking mirrors.
-   Reserve full issue-native review workflow changes for phase 2 automation once command/auth controls are implemented.
-   Preserve the current `dev -> sec -> docs` sequential delegation protocol until phase 2 lands.

### Step 4 — Document Transition of Old Commands

Update `README.md` and docs-agent instruction files (`.gemini/docs-agent.md`, `skills/docs-agent.md`) to:
-   Clarify that `docs roadmap-sync` is superseded by GitHub issue tracking and will be retired after migration.
-   Clarify that `docs align-sync` is *not* affected by this migration (it handles README/config/env synchronization, which remains useful).
-   Provide operator guidance for mixed-mode operation during transition.

### Step 5 — Plan for Automated GitHub Interaction (Future Feature)

Track phase 2 in a dedicated feature doc:
-   The requirements for agents to directly interact with the GitHub API.
-   Security considerations for `GITHUB_REPO_TOKEN`.
-   Proposed tools/libraries for GitHub API integration.
-   Reference: `docs/features/github-issues-automation-phase2.md`.

### Step 6 — Cleanup Old Documentation System (Post-Migration, separate PR)

Once all features are successfully migrated and verified on GitHub:
-   Delete `docs/roadmap.md`.
-   Remove only migrated legacy files in `docs/features/`, preserving any still-active specs until their issue parity is confirmed.
-   Track cleanup in `docs/features/github-issues-cleanup.md`.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `.github/ISSUE_TEMPLATE/feature.md` | **Create** | New template for feature requests. |
| `.gitignore` | **Edit** | Add `tmp/` to prevent accidental commit of export artifacts. |
| `scripts/migrate_features.py` | **Create** | Python script for migrating feature docs to GitHub issue Markdown. |
| `docs/guides/feature-review-process.md` | **Edit** | Add mixed-mode migration guidance while preserving current `dev -> sec -> docs` delegation in phase 1. |
| `README.md` | **Edit** | Document migration workflow and mixed-mode transition guidance. |
| `.gemini/docs-agent.md` and/or `skills/docs-agent.md` | **Edit** | Update docs-agent instructions for issue-centric workflow and transition period. |
| `docs/features/github-issues-automation-phase2.md` | **Create** | Follow-up feature doc for automated issue CRUD with mandatory security review. |
| `docs/features/github-issues-cleanup.md` | **Create** | Follow-up feature doc tracking legacy docs cleanup work after parity verification. |
| `docs/features/github-issues-migration.md` | **Edit** | Track design decisions, phased scope, and review outcomes for this migration feature. |
| `docs/roadmap.md` | **Delete** | Only after verified parity report (separate cleanup PR). |
| `docs/features/*` | **Delete** | Remove migrated legacy specs incrementally after parity confirmation. |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| _None (phase 1)_ | ✅ No new dependency | Export script uses Python stdlib only. |
| `gh` CLI | ✅ Already used in project ops | Preferred audited path for future automation (phase 2). |

---

## Test Plan

### Unit Tests for `scripts/migrate_features.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_parse_feature_doc_sections` | Correctly parses various sections from feature documents. |
| `test_generate_github_issue_md_format` | Generated Markdown adheres to the GitHub issue template format. |
| `test_parse_feature_doc_edge_cases` | Handles missing status metadata and sparse section layouts, including docs with leading blank lines before `# Title`. |
| `test_parse_adversarial_content_literal_passthrough` | Feature docs containing shell metacharacters (`$(...)`, `` `...` ``), HTML/script tags, or embedded instructions in code blocks are passed through as literal text — no interpretation or execution. |
| `test_label_values_are_sanitized` | Punctuation-heavy `status`/`priority` values are normalized to safe label slugs (`[a-z0-9-]`) before export. |
| `test_verify_parity_report_passes_roundtrip` | `verify_parity_report()` accepts a clean export/parity set with no errors. |
| `test_verify_parity_report_detects_tampered_export` | `verify_parity_report()` flags hash drift if exported markdown is modified after parity generation. |
| `test_verify_parity_report_detects_metadata_drift` | `verify_parity_report()` detects parity report field drift (`title`, `labels`, etc.) versus live source parsing. |
| `test_verify_parity_report_detects_tampered_export_with_updated_hash` | `verify_parity_report()` rejects manipulated exports even when `output_sha256` is maliciously updated in the report. |

### Manual Verification of Migration

-   Run `scripts/migrate_features.py` and manually inspect the generated Markdown files for accuracy and completeness.
-   Manually create GitHub issues from the generated Markdown and verify their appearance on GitHub (labels, title, content).
-   Confirm `tmp/feature-issue-export/parity-report.json` has 1:1 mapping for every `docs/features/*.md` source (excluding `_template.md`).
-   Confirm each parity item includes `source_sha256` and `output_sha256`; use these hashes to ensure reviewed export artifacts are exactly the ones posted to GitHub.
-   Run `python scripts/migrate_features.py --verify` before posting to GitHub; verification must pass with zero mismatches.
-   `--verify` now enforces parity content consistency (title/slug/status/priority/labels) and deterministic render matching, reducing reliance on manual report spot-checking alone.

### End-to-End Review Process Simulation

-   Simulate mixed-mode review with agents (`dev -> sec -> docs`) and verify issue links are attached without replacing the existing delegation protocol in phase 1.

---

## Documentation Updates

### `README.md`

-   Add a note that `docs roadmap-sync` is superseded by GitHub issue tracking during migration. `docs align-sync` is *not* deprecated — it continues to handle README/config/env synchronization.

### `.env.example` and `docker-compose.yml.example`

-   If automation requires explicit operator setup, add commented `GITHUB_REPO_TOKEN` guidance (scope + rotation notes).

### `docs/roadmap.md`

-   After successful migration, this file will be deleted.

### `docs/features/github-issues-migration.md`

-   Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.
-   Add `Implemented in: vX.Y.Z` below the status line.

---

## Version Bump

Consult `docs/versioning.md` for the full decision guide.

**Expected bump for this feature**: `MINOR` (new capability and process additions without immediate breaking runtime behavior).  
If/when destructive cleanup removes user-facing workflows, re-evaluate at that time per `docs/versioning.md`.

---

## Roadmap Update

When phase 1 is complete, GitHub issues become the preferred tracking surface while `docs/roadmap.md` remains temporarily for cross-checking.  
Delete `docs/roadmap.md` only in cleanup phase after parity is validated.

---

## Edge Cases and Open Questions

1.  **Partial Migration Handling**: What is the strategy if only a subset of feature documents are migrated? How do we ensure consistency during a transitional period?
2.  **Rollback Strategy**: What is the process for rolling back if the new GitHub-centric system proves problematic?
3.  **Agent GitHub Authentication**: What least-privilege scope is required for `GITHUB_REPO_TOKEN`, and how is rotation/audit handled for automated interactions?
    > *Proposed*: For Phase 2, require a fine-grained PAT with `issues:write` and `metadata:read` only. Full `repo` scope must NOT be used for issue automation. Document required scopes in `.env.example`. Token rotation: recommend 90-day expiry; `_validate_config()` can warn if the token lacks expected scopes (via `gh auth status`).
4.  **Consistency Across AI CLIs**: How will the different AI CLIs (Codex, Gemini, Autopilot) ensure consistent interaction with GitHub issues, especially regarding automated actions and review processes?
5.  **External User Interaction**: How will external users (e.g., community contributors) be guided through the new GitHub issue creation and review process?
    > *Proposed*: External contributors use the `feature.md` issue template like any other GitHub project — no special onboarding beyond the template's built-in guidance. Externally-submitted issue content is untrusted and must never be fed to `run_shell()`, interpolated into `gh` commands, or processed by the migration script without manual review. Phase 2 automation must treat all issue body content as untrusted input, applying the same `shlex.quote()` / `--body-file` sanitization defined in Architecture Notes.
6.  **Migration Verification**: What are the definitive criteria for verifying that all features have been successfully migrated to GitHub issues before deleting the old documentation?

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

-   [x] All implementation steps for the migration phase (Step 1-4) are complete.
-   [x] `scripts/migrate_features.py` is created and successfully generates valid Markdown for all existing feature documents.
-   [x] The new GitHub `feature.md` issue template is created and correctly formatted for migrated specs.
-   [x] `docs/guides/feature-review-process.md` is updated for mixed-mode migration (current review chain preserved during phase 1).
-   [x] `README.md` and docs-agent instructions (`.gemini/docs-agent.md` and/or `skills/docs-agent.md`) are updated with migration/transition guidance.
-   [ ] Manual verification of migrated issues on GitHub confirms accuracy and completeness.
-   [x] The team has approved the new review process.
-   [x] A parity report (`tmp/feature-issue-export/parity-report.json`) confirms every migrated feature doc has a corresponding GitHub issue with mapped status/priority labels and deterministic `source_sha256`/`output_sha256` integrity hashes.
-   [x] Cleanup work (`docs/roadmap.md` and migrated legacy docs removal) is tracked in a follow-up PR/feature.
-   [x] Phase 2 (automated GitHub interaction) has its own feature doc with a security review requirement before implementation. `docs align-sync` is confirmed retained and not deprecated by this migration.
-   [ ] The `VERSION` file bump follows `docs/versioning.md` for the exact delivered scope.
-   [x] All agents are briefed and capable of following the mixed-mode migration process for phase 1.
-   [x] `pytest tests/ -v --tb=short` passes with no failures or errors (after script implementation).
-   [x] `ruff check src/` reports no new linting issues (after script implementation).
-   [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
