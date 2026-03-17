# GitHub Issue Migration for Feature Tracking

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-17

This feature outlines the plan to convert all existing feature documents in `docs/features/` into GitHub issues for streamlined prioritization and tracking. It also details the removal of the old documentation system (`docs/roadmap.md` and `docs/features/` directory) and the automation of the issue creation and review process.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/github-issues-migration.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1.  **Scope** — This applies across all platforms as it is an internal process change.
2.  **Backend** — This is independent of AI backends.
3.  **Stateful vs stateless** — N/A.
4.  **Breaking change?** — Yes, it removes existing documentation files and changes the feature tracking process, requiring a MAJOR version bump.
5.  **New dependency?** — Potentially for GitHub API interaction libraries in the automation phase.
6.  **Persistence** — N/A.
7.  **Auth** — Yes, for automated GitHub issue creation and management, agents will need GitHub API tokens. These would be stored in `config.py`.
8.  **Automated GitHub Interaction** — Is it feasible for agents (Gemini, Codex, Autopilot) to directly create, update, and manage GitHub issues? This is a critical dependency for full automation.

---

## Problem Statement

1.  **Manual Synchronization**: The current `docs/features/` and `docs/roadmap.md` system requires manual updates, leading to inconsistencies and stale information.
2.  **Lack of Integrated Prioritization**: Features are not prioritized within a dynamic system, making it difficult to re-prioritize and track progress effectively.
3.  **Inefficient Review Process**: The current feature review process is document-centric, requiring manual delegation and status updates, which is not scalable or easily auditable.
4.  **Limited Automation**: The existing `docs roadmap-sync` and `docs align-sync` commands only address a small part of the documentation lifecycle and are not integrated with project management tools.
5.  **Disparate Systems**: Feature planning, tracking, and development are spread across different systems (documentation, code, chat), leading to overhead and potential miscommunication.

---

## Current Behaviour (as of v0.7.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Docs | `docs/features/*.md` | Individual feature specifications, manually updated. |
| Docs | `docs/roadmap.md` | Centralized list of features and their status, manually updated. |
| Commands | `docs roadmap-sync` | Synchronizes `docs/features/` and `docs/roadmap.md`, intended to keep them aligned but requires manual trigger and doesn't fully automate. |
| Commands | `docs align-sync` | Synchronizes `README.md`, `.env.example`, `docker-compose.yml.example`, and `src/config.py`, also requires manual trigger. |
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

-   **Automated Migration Script**: Develop a Python script to parse `docs/features/*.md` files, extract relevant information, and generate GitHub-compatible Markdown content for feature issues. This script will be user-executable for the initial migration phase.
-   **GitHub Issue Templates**: Create `bug.md`, `feature.md`, and `improvement.md` templates in `.github/ISSUE_TEMPLATE/` to standardize issue creation for external users and internal teams.
-   **Automated Issue Creation (Future Phase)**: Investigate and implement capabilities for agents to securely and persistently interact with the GitHub API to fully automate issue creation, updates, and management. This will be a follow-up feature.
-   **Updated Review Process**: Revise `docs/guides/feature-review-process.md` to define a new GitHub-issue-centric review process. This process will use GitHub issue descriptions for content, labels for status and priority, and comments for reviewer feedback, scores, and delegation among GateCode, GateSec, and GateDocs.
-   **Deprecation of Old System**: Deprecate and eventually remove `docs/roadmap.md` and the `docs/features/` directory (excluding `_template.md` which will also be removed once new templates are in use) after successful migration and verification. The `docs roadmap-sync` and `docs align-sync` commands will also be deprecated and removed from agent instructions.

---

## Architecture Notes

-   **Agent GitHub Interaction**: A critical architectural consideration is the secure and persistent authentication and authorization of agents (Gemini, Codex, Autopilot) to interact with the GitHub API. This requires either a dedicated GitHub API tool or a robust method for injecting `GH_TOKEN` securely into agent execution environments.
-   **Template Consistency**: The migration script and new templates must ensure consistency in information capture from the old feature documents to the new GitHub issues.
-   **Backward Compatibility**: Ensure a graceful transition for any ongoing features during the migration period.
-   **Scalability**: The new process should be scalable to accommodate a growing number of features and agents.

---

## Config Variables

Initially, no new configuration variables are required for the migration phase (Option A). However, for the automated issue creation (Option B, future state), the following might be needed:

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `GITHUB_API_TOKEN` | `str` | `""` | GitHub Personal Access Token for automated issue management. |

---

## Implementation Steps

### Step 1 — Create GitHub Issue Templates

Create the following files in `.github/ISSUE_TEMPLATE/`:
-   `bug.md` (for bug reports)
-   `feature.md` (for feature requests, mirroring the migrated feature docs)
-   `improvement.md` (for general improvements)

### Step 2 — Develop Feature Document Migration Script

Create a Python script (e.g., `scripts/migrate_features.py`) that:
-   Parses existing `docs/features/*.md` files.
-   Extracts key information (title, overview, problem statement, design, env vars, files to change, etc.).
-   Generates Markdown content formatted according to the new `feature.md` GitHub issue template.
-   Outputs these generated Markdown files to a temporary directory for user review and manual GitHub issue creation.

### Step 3 — Update Feature Review Process Guide

Revise `docs/guides/feature-review-process.md` to:
-   Describe the new GitHub-issue-centric review workflow.
-   Detail how agents will use GitHub labels (`review: pending`, `review: approved`), assignees, and comments for managing the review lifecycle.
-   Provide clear instructions for each agent (GateCode, GateSec, GateDocs) on their role in the new process.

### Step 4 — Document Deprecation of Old Commands

Update `README.md` and `docs-agent.md` (or `GEMINI.md`) to:
-   Announce the deprecation of the `docs roadmap-sync` and `docs align-sync` commands.
-   Provide a brief explanation of why these commands are being deprecated (moving to GitHub-centric management).

### Step 5 — Plan for Automated GitHub Interaction (Future Feature)

Outline a separate feature document or a section in this document detailing:
-   The requirements for agents to directly interact with the GitHub API.
-   Security considerations for `GITHUB_API_TOKEN`.
-   Proposed tools/libraries for GitHub API integration.

### Step 6 — Delete Old Documentation System (Post-Migration)

Once all features are successfully migrated and verified on GitHub:
-   Delete `docs/roadmap.md`.
-   Delete the entire `docs/features/` directory (including `_template.md`).

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `.github/ISSUE_TEMPLATE/bug.md` | **Create** | New template for bug reports. |
| `.github/ISSUE_TEMPLATE/feature.md` | **Create** | New template for feature requests. |
| `.github/ISSUE_TEMPLATE/improvement.md` | **Create** | New template for improvement requests. |
| `scripts/migrate_features.py` | **Create** | Python script for migrating feature docs to GitHub issue Markdown. |
| `docs/guides/feature-review-process.md` | **Edit** | Update review process to be GitHub-issue-centric. |
| `README.md` | **Edit** | Document deprecation of old `docs` commands. |
| `docs-agent.md` (or `GEMINI.md`) | **Edit** | Document deprecation of old `docs` commands. |
| `docs/features/github-issues-migration.md` | **Create** | This feature document. |
| `docs/roadmap.md` | **Delete** | After successful migration. |
| `docs/features/` | **Delete** | Entire directory, after successful migration. |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `PyGithub` (or similar) | ❌ Needs adding (future) | For automated GitHub API interaction in Option B. |

---

## Test Plan

### Unit Tests for `scripts/migrate_features.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_parse_feature_doc_sections` | Correctly parses various sections from feature documents. |
| `test_generate_github_issue_md_format` | Generated Markdown adheres to the GitHub issue template format. |
| `test_parse_feature_doc_edge_cases` | Handles missing sections or malformed markdown gracefully. |

### Manual Verification of Migration

-   Run `scripts/migrate_features.py` and manually inspect the generated Markdown files for accuracy and completeness.
-   Manually create GitHub issues from the generated Markdown and verify their appearance on GitHub (labels, title, content).

### End-to-End Review Process Simulation

-   Simulate the new GitHub-issue-centric review process with agents using a test GitHub issue, verifying correct label application, comment format, and delegation.

---

## Documentation Updates

### `README.md`

-   Add a note about the deprecation of `docs roadmap-sync` and `docs align-sync` under a "Deprecated Commands" section or similar.

### `.env.example` and `docker-compose.yml.example`

-   If `GITHUB_API_TOKEN` is introduced in a future phase, add commented entries with descriptions.

### `docs/roadmap.md`

-   After successful migration, this file will be deleted.

### `docs/features/github-issues-migration.md`

-   Change `Status: **Planned**` → `Status: **Implemented**` on merge to `main`.
-   Add `Implemented in: vX.Y.Z` below the status line.

---

## Version Bump

Consult `docs/versioning.md` for the full decision guide.

**Expected bump for this feature**: `MAJOR` → `1.0.0` (due to removal of existing documentation system and significant workflow changes).

---

## Roadmap Update

When this feature is complete, `docs/roadmap.md` will be deleted. The GitHub issue board will serve as the new roadmap.

---

## Edge Cases and Open Questions

1.  **Partial Migration Handling**: What is the strategy if only a subset of feature documents are migrated? How do we ensure consistency during a transitional period?
2.  **Rollback Strategy**: What is the process for rolling back if the new GitHub-centric system proves problematic?
3.  **Agent GitHub Authentication**: How will `GITHUB_API_TOKEN` be managed securely and persist across agent sessions for automated GitHub interactions? This is crucial for full automation.
4.  **Consistency Across AI CLIs**: How will the different AI CLIs (Codex, Gemini, Autopilot) ensure consistent interaction with GitHub issues, especially regarding automated actions and review processes?
5.  **External User Interaction**: How will external users (e.g., community contributors) be guided through the new GitHub issue creation and review process?
6.  **Migration Verification**: What are the definitive criteria for verifying that all features have been successfully migrated to GitHub issues before deleting the old documentation?

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

-   [ ] All implementation steps for the migration phase (Step 1-4) are complete.
-   [ ] `scripts/migrate_features.py` is created and successfully generates valid Markdown for all existing feature documents.
-   [ ] The new GitHub issue templates (`bug.md`, `feature.md`, `improvement.md`) are created and correctly formatted.
-   [ ] `docs/guides/feature-review-process.md` is updated to reflect the GitHub-issue-centric review process.
-   [ ] `README.md` and `docs-agent.md` (or `GEMINI.md`) are updated with deprecation notices for old commands.
-   [ ] Manual verification of migrated issues on GitHub confirms accuracy and completeness.
-   [ ] The team has approved the new review process.
-   [ ] `docs/roadmap.md` is deleted.
-   [ ] The `docs/features/` directory is deleted.
-   [ ] The `VERSION` file is bumped to `MAJOR` (e.g., `1.0.0`).
-   [ ] All agents are briefed and capable of following the new GitHub-issue-centric review process.
-   [ ] `pytest tests/ -v --tb=short` passes with no failures or errors (after script implementation).
-   [ ] `ruff check src/` reports no new linting issues (after script implementation).
-   [ ] PR is merged to `develop` first; CI is green; then merged to `main`.
