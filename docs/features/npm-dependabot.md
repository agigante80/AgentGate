# npm Globals Not Covered by Dependabot

> Status: **Planned** | Priority: Low | Last reviewed: 2026-03-12

Add Dependabot coverage for `@github/copilot-cli` and `@openai/codex` npm packages, which are currently pinned in the Dockerfile but never auto-updated.

---

## ⚠️ Prerequisite Questions

1. **Scope** — Infrastructure/CI only. No change to bot behaviour on either platform.
2. **Backend** — Affects `copilot` and `codex` backends indirectly (keeps their CLIs up to date).
3. **Stateful vs stateless** — Not applicable.
4. **Breaking change?** — No. The Dependabot PRs it generates are reviewed before merge.
5. **New dependency?** — A `package.json` at the repo root. This file is never `npm install`-ed in production; it exists purely as a Dependabot manifest.
6. **Persistence** — No storage changes.
7. **Auth** — No new secrets. Dependabot uses the existing `GITHUB_TOKEN`.
8. **Dockerfile comment accuracy** — The Dockerfile already has the comment `# pinned version (update via Dependabot)` on both npm lines, implying this was always the intent.

---

## Problem Statement

1. **Silent staleness** — `@github/copilot@0.0.421` and `@openai/codex@0.111.0` are hardcoded in `Dockerfile:30,33`. Security patches and bug fixes in these CLIs are never picked up automatically.
2. **Manual toil** — Developers must monitor each CLI's GitHub Releases page and update the Dockerfile pin by hand. This is easy to forget.
3. **Inconsistency** — Python, Docker base image, and GitHub Actions are all covered by Dependabot (`.github/dependabot.yml` already has three `updates` entries). npm globals are the only blind spot.

---

## Current Behaviour (as of v0.8.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Dockerfile | `Dockerfile:30` | `RUN npm install -g @github/copilot@0.0.421` — hardcoded, never updated |
| Dockerfile | `Dockerfile:33` | `RUN npm install -g @openai/codex@0.111.0` — hardcoded, never updated |
| Dependabot | `.github/dependabot.yml` | Covers `pip`, `github-actions`, `docker` — no `npm` entry |
| package.json | *(missing)* | No `package.json` exists at repo root |

> **Key gap**: Dependabot's `npm` ecosystem requires a `package.json` (or `package-lock.json`) to track dependencies. Without one, it has nothing to scan.

---

## Design Space

### Axis 1 — How to make Dependabot aware of npm globals

#### Option A — Manual monitoring *(status quo)*

Watch each CLI's release page, update `Dockerfile` pins by hand.

**Pros:** No new files.
**Cons:** Relies on developer discipline; security patches will be missed.

---

#### Option B — Root `package.json` as Dependabot manifest *(recommended)*

Add a minimal `package.json` at the repo root listing the two CLIs as `dependencies`. Dependabot's `npm` ecosystem scanner will detect version bumps and open PRs that update both `package.json` and the `Dockerfile` pin.

```json
{
  "name": "agentgate-npm-manifest",
  "private": true,
  "description": "Dependabot manifest for npm globals installed in Dockerfile.",
  "dependencies": {
    "@github/copilot": "0.0.421",
    "@openai/codex": "0.111.0"
  }
}
```

The Dockerfile pins must be kept in sync manually when Dependabot PRs update `package.json`. A CI step can enforce this (see Option C).

**Pros:** Minimal friction, no new tooling, follows the standard Dependabot pattern.
**Cons:** Requires developer to update the Dockerfile pin alongside the `package.json` bump (Dependabot cannot edit `Dockerfile` npm pins automatically).

---

#### Option C — GitHub Actions outdated check

Add a CI job that runs `npm outdated --json` against a temporary `node_modules` install and fails the build if versions are stale.

**Pros:** Actively blocks stale PRs.
**Cons:** Requires an `npm install` step in CI (slow); adds complexity; still requires manual Dockerfile edits.

---

**Recommendation: Option B** — lowest friction, follows the existing Dependabot pattern, no new tooling required.

---

## Recommended Solution

- **Axis 1**: Option B — add `package.json` + `npm` entry to `.github/dependabot.yml`.

Dependabot will open weekly PRs when either CLI releases a new version. The PR description will reference the changelog. The developer updates both `package.json` and the matching `Dockerfile` pin in the same PR before merging.

---

## Architecture Notes

- The `package.json` is **never installed** in production or CI. It is a metadata-only manifest for Dependabot. Add a `private: true` field and a clear `description` to make this intent obvious.
- Dependabot's `npm` ecosystem scanner reads `package.json` at the configured `directory`. Using `/` (repo root) matches the existing pip and docker entries.
- The two Dockerfile lines already carry the comment `# pinned version (update via Dependabot)` — this change fulfils that comment.

---

## Config Variables

N/A — no new env vars.

---

## Implementation Steps

### Step 1 — Create `package.json` at repo root

```json
{
  "name": "agentgate-npm-manifest",
  "private": true,
  "description": "Dependabot manifest only — not installed in production. Keep versions in sync with Dockerfile.",
  "dependencies": {
    "@github/copilot": "0.0.421",
    "@openai/codex": "0.111.0"
  }
}
```

---

### Step 2 — Add `npm` entry to `.github/dependabot.yml`

Append to the existing `updates` list:

```yaml
  # npm globals (@github/copilot-cli, @openai/codex) — manifest in package.json
  - package-ecosystem: npm
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "06:00"
      timezone: UTC
    open-pull-requests-limit: 5
    labels:
      - dependencies
      - npm
```

---

### Step 3 — Verify Dependabot config is valid

```bash
# No CLI tool available; verify by pushing to develop and checking
# GitHub → Settings → Code security → Dependabot → Recent activity
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `package.json` | **Create** | Dependabot npm manifest with current pinned versions |
| `.github/dependabot.yml` | **Edit** | Add `npm` ecosystem entry |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| No new packages | ✅ N/A | `package.json` is metadata-only; not `npm install`-ed |

---

## Test Plan

No automated tests — this is a CI/config-only change. Verification is:

1. Push `package.json` + updated `dependabot.yml` to `develop`.
2. Go to GitHub → Insights → Dependency graph → Dependabot → check that npm ecosystem appears.
3. Optionally trigger a manual Dependabot run (GitHub → Security → Dependabot → "Check for updates").
4. Confirm Dependabot opens a PR if either package has a newer version.

---

## Documentation Updates

### `README.md`

No change — this is an internal maintenance improvement invisible to users.

### `.github/copilot-instructions.md`

No change needed.

### `docs/roadmap.md`

Mark item 1.2 as ✅ once `package.json` and `dependabot.yml` are merged to `main`.

---

## Version Bump

No version bump — no production code changes.

---

## Acceptance Criteria

- [ ] `package.json` exists at repo root with correct versions matching `Dockerfile:30,33`.
- [ ] `.github/dependabot.yml` has an `npm` entry pointing to `/`.
- [ ] GitHub Dependabot dashboard shows npm ecosystem listed for this repository.
- [ ] `docs/roadmap.md` item 1.2 is marked done (✅).
- [ ] `docs/features/npm-dependabot.md` status changed to `Implemented` on completion.
