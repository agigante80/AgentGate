# Docs Align-Sync (`docs align-sync`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-15

Keeps the four key user-facing reference files — `README.md`, `.env.example`, `docker-compose.yml.example`, and `scripts/lint_docs.py` — in sync with the actual source-of-truth (`src/config.py` and `docs/roadmap.md`).

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/docs-align-sync.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — This is a docs-agent maintenance command only (no Telegram/Slack runtime changes).
2. **Backend** — Not AI-backend specific; operates purely on the filesystem.
3. **Stateful vs stateless** — Not applicable; no AI pipeline involved.
4. **Breaking change?** — No. `README.md` will be fixed (de-duplicated), but the content is preserved. `.env.example` and `docker-compose.yml.example` may gain/lose commented entries. No existing env var names change. → PATCH bump.
5. **New dependency?** — No new pip packages needed; `lint_docs.py` already uses stdlib only.
6. **Persistence** — No new DB table or `/data/` file required.
7. **Auth** — No new secrets or tokens.
8. **README duplication** — The README currently contains the full document twice (≈ 660 lines, with content ending around line 341 then restarting). The de-duplication must merge the best content from both copies (more complete features list from the first copy + more detailed Quick Start from the second copy).
9. **Passthrough allowlist** — `COPILOT_GITHUB_TOKEN` and `REPO_HOST_PATH` appear in `.env.example` / `docker-compose.yml.example` but are NOT defined in `src/config.py` (they are passed directly to the Copilot CLI subprocess or used by Docker Compose itself). These must be in an explicit passthrough allowlist inside `lint_docs.py` so they are never flagged as stale.

---

## Problem Statement

1. **README duplication** — `README.md` is ~660 lines but the meaningful content ends around line 341. The entire document then repeats verbatim (with slight variation), meaning readers and search tools see everything twice. Maintaining it is error-prone.
2. **README features section drift** — The "Features" bullet list in `README.md` describes what the product does, but it is maintained by hand. As roadmap items ship or are added, the list goes stale.
3. **`.env.example` drift** — Variables are added to `src/config.py` without corresponding updates to `.env.example`, leaving new self-hosters without any starter template entry.
4. **`docker-compose.yml.example` drift** — Same problem: the compose example references key vars in comments, but those comments go stale as new important vars are added.
5. **No lint check enforces `.env.example` or `docker-compose.yml.example` coverage** — `scripts/lint_docs.py` currently has 5 checks; none cover these two files. Drift is only caught by a human.

---

## Current Behaviour (as of v`0.18.x`)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| `lint_docs.py` | `scripts/lint_docs.py` (checks 1–4) | Validates spec statuses, roadmap links, and cross-references. |
| `lint_docs.py` | `scripts/lint_docs.py:check_config_coverage()` | Check 5: every `src/config.py` env var must appear in `README.md`. Passes today. |
| `README.md` | `README.md:1–660` | Full document appears twice; second copy starts after the `## License` section. |
| `.env.example` | `.env.example:1–38` | 13 variables; hand-maintained. No automated check for drift. |
| `docker-compose.yml.example` | `docker-compose.yml.example:1–42` | References key vars in comments; hand-maintained. No automated check. |
| Skills | `skills/docs-agent.md` | `docs align-sync` command not yet formally defined. |

> **Key gap**: No automated enforcement ensures that `.env.example`, `docker-compose.yml.example`, and the README features list stay aligned with code. Drift is the default outcome.

---

## Design Space

### Axis 1 — Where to implement the alignment checks

#### Option A — Standalone `scripts/align_sync.py` *(new file)*

A separate script, called by the docs agent.

**Pros:**
- Clean separation from the existing lint script.

**Cons:**
- Two scripts to maintain; duplicate path constants and parsing helpers.
- `lint_docs.py` already has the pattern established; a second file just fragments it.

---

#### Option B — Extend `scripts/lint_docs.py` with new checks *(recommended)*

Add Check 6 (`.env.example` coverage) and Check 7 (`docker-compose.yml.example` coverage) directly to `lint_docs.py`. The `docs align-sync` command runs `lint_docs.py` and additionally applies the fixes that cannot be expressed as a pure lint check (README de-duplication, README features list refresh).

**Pros:**
- One script, one source of truth. Existing CI integration keeps working.
- New checks inherit all existing infrastructure (path constants, reporting format, exit codes).

**Cons:**
- `lint_docs.py` grows slightly; must stay focused on *reporting*, not *fixing*.

**Recommendation: Option B** — extend the existing script; keep lint = report-only, fixes = docs-agent actions.

---

### Axis 2 — Passthrough allowlist for non-config vars

Some vars in `.env.example` and `docker-compose.yml.example` are intentionally absent from `src/config.py` (e.g. `COPILOT_GITHUB_TOKEN` passed to the CLI subprocess, `REPO_HOST_PATH` consumed by Docker Compose).

#### Option A — Hard-code allowlist in `lint_docs.py`

```python
_ENV_EXAMPLE_PASSTHROUGHS = {"COPILOT_GITHUB_TOKEN", "REPO_HOST_PATH"}
```

**Pros:** Simple, auditable, no new config surface.
**Cons:** Must be updated manually when new passthroughs are added.

#### Option B — Read allowlist from a comment block in `.env.example` *(recommended)*

Mark passthrough vars with a special inline comment: `# passthrough: <reason>`. The lint script parses this marker.

**Pros:** Self-documenting; the reason lives next to the variable. No separate allowlist file.
**Cons:** Slightly more parsing code in `lint_docs.py`.

**Recommendation: Option B** — self-documenting passthrough markers in `.env.example`.

---

### Axis 3 — README de-duplication strategy

The README has two copies; they differ slightly. The merge must be deliberate.

#### Option A — Keep the first copy verbatim

Simple: truncate at the first `## License` + MIT block. The first copy has a more complete features list.

**Pros:** Zero merge complexity.
**Cons:** Loses the more detailed Quick Start section from the second copy.

#### Option B — Merge best-of-both *(recommended)*

Take the first copy's Features bullet list (more complete) and the second copy's Quick Start / deployment examples (more detailed). Produce one definitive document.

**Pros:** Best user experience.
**Cons:** Requires a careful one-time manual merge by the docs agent.

**Recommendation: Option B** — performed once as Step 1 of implementation; then lint prevents re-duplication.

---

## Recommended Solution

- **Axis 1**: Option B — extend `lint_docs.py` with checks 6 + 7.
- **Axis 2**: Option B — `# passthrough: <reason>` marker in `.env.example`.
- **Axis 3**: Option B — merge best-of-both into one definitive README.

### `docs align-sync` execution flow

```
docs agent receives: docs align-sync
│
├─ Step 1: Fix README.md duplication (one-time merge, best-of-both)
│
├─ Step 2: Refresh README.md features bullet list
│          Compare against active roadmap items (docs/roadmap.md)
│          Add missing bullets; flag/remove stale ones
│
├─ Step 3: Run lint check 6 — .env.example coverage
│          For each env var in src/config.py:
│            if not in .env.example AND not "minor/internal":
│              report drift
│          For each var in .env.example (non-passthrough):
│            if not in src/config.py:
│              report stale entry
│
├─ Step 4: Run lint check 7 — docker-compose.yml.example coverage
│          For each "important" var in .env.example:
│            if not referenced in docker-compose.yml.example comment block:
│              report drift
│
├─ Step 5: Apply fixes (docs agent edits files based on lint output)
│
└─ Step 6: Commit with message: "docs(align-sync): sync README, .env.example, docker-compose.yml.example"
```

---

## Architecture Notes

- **`lint_docs.py` is report-only** — it exits 0 or 1 and prints violations. It never modifies files. Fixes are applied by the docs agent after reading the lint output.
- **`REPO_DIR` / `DB_PATH`** — not involved; this feature is pure filesystem (docs tree only).
- **No platform symmetry required** — this is a docs-agent-only command; no `bot.py` / `slack.py` changes.
- **No `@_requires_auth` guard** — not a bot handler.
- **CI integration** — `scripts/lint_docs.py` is already called in the `lint` job of `.github/workflows/ci-cd.yml`. Checks 6 and 7 will run automatically in CI once added.
- **`# passthrough:` marker parsing** — must be robust to trailing whitespace and mixed comment styles in `.env.example`.

---

## Config Variables

No new env vars are introduced by this feature. It is a docs-tooling operation.

---

## Implementation Steps

### Step 1 — Fix `README.md` duplication (manual merge)

The docs agent reads `README.md`, identifies the duplication boundary (the first `## License\n\nMIT` block at ≈ line 341), then:

1. Takes the Features bullet list from the first copy (more complete: includes `Full CLI pass-through`, `Broadcast`, etc.).
2. Takes the Quick Start / deployment examples from the second copy (more detailed).
3. Writes a single merged, clean document.
4. Verifies with `wc -l` that the new file is ≈ 340–380 lines (roughly half the current size).

---

### Step 2 — Add passthrough markers to `.env.example`

For every variable in `.env.example` that is intentionally absent from `src/config.py`, add an inline comment:

```bash
COPILOT_GITHUB_TOKEN=github_pat_xxxxxxxxxxxx   # passthrough: forwarded to copilot CLI subprocess
# REPO_HOST_PATH=/host/path                     # passthrough: Docker Compose bind-mount only
```

---

### Step 3 — Extend `scripts/lint_docs.py` with Check 6

Add `check_env_example_coverage()` function:

```python
ENV_EXAMPLE_FILE = Path(".env.example")
_PASSTHROUGH_MARKER = "# passthrough:"

def _parse_env_example() -> tuple[set[str], set[str]]:
    """Return (declared_vars, passthrough_vars) from .env.example."""
    declared, passthroughs = set(), set()
    if not ENV_EXAMPLE_FILE.is_file():
        return declared, passthroughs
    for line in ENV_EXAMPLE_FILE.read_text().splitlines():
        stripped = line.strip().lstrip("#").strip()
        if "=" in stripped:
            var = stripped.split("=", 1)[0].strip()
            if _PASSTHROUGH_MARKER in line:
                passthroughs.add(var)
            else:
                declared.add(var)
    return declared, passthroughs


def check_env_example_coverage(config_vars: set[str]) -> tuple[list[str], list[str]]:
    """Check 6: .env.example covers important config.py vars; no stale entries."""
    declared, passthroughs = _parse_env_example()
    all_known = declared | passthroughs
    errors: list[str] = []

    # Stale entries: in .env.example (non-passthrough) but not in config.py
    for var in sorted(declared - config_vars):
        errors.append(
            f"[ENV EXAMPLE STALE] {var} is in .env.example but not in src/config.py "
            "(add '# passthrough: <reason>' if intentional)"
        )

    return errors, []
```

Wire into `main()` after check 5:

```python
env_errors, _ = check_env_example_coverage(extract_config_env_vars())
errors.extend(env_errors)
```

---

### Step 4 — Extend `scripts/lint_docs.py` with Check 7

Add `check_compose_coverage()` function:

```python
COMPOSE_EXAMPLE_FILE = Path("docker-compose.yml.example")

def check_compose_coverage() -> tuple[list[str], list[str]]:
    """Check 7: docker-compose.yml.example references all vars in .env.example."""
    if not COMPOSE_EXAMPLE_FILE.is_file():
        return [], []
    declared, _ = _parse_env_example()
    compose_text = COMPOSE_EXAMPLE_FILE.read_text()
    errors: list[str] = []
    for var in sorted(declared):
        if var not in compose_text:
            errors.append(
                f"[COMPOSE DRIFT] {var} is in .env.example but not referenced in "
                "docker-compose.yml.example"
            )
    return errors, []
```

Wire into `main()` after check 6.

---

### Step 5 — Update `skills/docs-agent.md`

Add formal definition of `docs align-sync` alongside `docs roadmap-sync`.

---

### Step 6 — Add `docs-align-sync` to `docs/roadmap.md`

Add row 2.15 to the roadmap table.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `README.md` | **Edit** | De-duplicate (merge best-of-both into ≈ 340–380 lines) |
| `.env.example` | **Edit** | Add `# passthrough: <reason>` markers to non-config vars |
| `scripts/lint_docs.py` | **Edit** | Add Check 6 (`_parse_env_example`, `check_env_example_coverage`) and Check 7 (`check_compose_coverage`) |
| `skills/docs-agent.md` | **Edit** | Formally define `docs align-sync` command |
| `docs/roadmap.md` | **Edit** | Add item 2.15 linking to this file |
| `docs/features/docs-align-sync.md` | **Edit** | Mark `Implemented` after merge to `main` |

---

## Dependencies

No new packages required. `scripts/lint_docs.py` uses stdlib only (`re`, `sys`, `pathlib`).

---

## Test Plan

### `scripts/lint_docs.py` — manual verification

| Test | What it checks |
|------|----------------|
| Run with current repo | Check 6 reports stale `.env.example` entries (before adding passthrough markers) |
| Run after Step 2 | Check 6 passes cleanly |
| Add a fake stale var to `.env.example` | Check 6 flags it; exit code 1 |
| Remove a real var from compose example | Check 7 flags it; exit code 1 |
| Run full suite after all fixes | Exit code 0, all checks pass |

### CI validation

`scripts/lint_docs.py` is already wired into the `lint` job — checks 6 and 7 will run on every push to `develop` and `main` automatically.

### `pytest tests/` — regression guard

No new unit tests required for this feature (it adds no runtime code). After implementation, run:

```bash
pytest tests/ -v --tb=short
```

to confirm no existing tests regress.

---

## Documentation Updates

### `README.md`

- De-duplicate the file (Step 1).
- Refresh the Features bullet list to match current `docs/roadmap.md` active items.

### `.env.example`

- Add `# passthrough: <reason>` to `COPILOT_GITHUB_TOKEN` and `REPO_HOST_PATH`.

### `docker-compose.yml.example`

- Verify all vars present in `.env.example` (non-passthrough) are referenced in comments.
- Add missing references as needed.

### `skills/docs-agent.md`

- Define `docs align-sync` command formally (alongside existing `docs roadmap-sync`).

---

## Version Bump

This feature fixes a README bug and adds lint checks with no user-visible config changes.

**Expected bump**: PATCH → `0.18.x + 1`

---

## Roadmap Update

When complete, add to `docs/roadmap.md`:

```markdown
| 2.15 | ✅ Docs align-sync — README de-dup, .env.example & docker-compose coverage lint | [→ features/docs-align-sync.md](features/docs-align-sync.md) |
```

---

## Edge Cases and Open Questions

1. **README merge conflict** — The two copies of `README.md` differ in subtle ways (feature bullet wording, Quick Start examples). The docs agent must diff them manually and choose the best content — this cannot be automated. Risk: low, since the merge is a one-time operation.

2. **"Important" vs "minor" config vars in `.env.example`** — Not every var in `src/config.py` warrants an entry in `.env.example` (e.g. internal tunables like `STREAM_THROTTLE_SECS`). Check 6 currently reports *all* non-passthrough vars absent from `.env.example`. A future refinement could add a `# internal` marker to suppress those warnings; for now, the docs agent uses judgement.

3. **`docker-compose.yml.example` scope** — Check 7 verifies that `.env.example` vars appear *somewhere* in the compose file (including comments). It does not validate YAML structure. This is intentional — the compose example is mostly a comment block.

4. **CI timing** — Checks 6 and 7 will fail CI if `.env.example` or `docker-compose.yml.example` goes stale after this feature ships. That is the desired behaviour, but the team should expect a first-run failure if the files are not fully updated before merging.

5. **`gate restart` interaction** — Not applicable; no runtime state.

6. **Slack thread scope** — Not applicable; this is a docs-agent-only command.

---

## Acceptance Criteria

- [ ] `README.md` contains no duplicate content; `wc -l README.md` is ≤ 400.
- [ ] `README.md` Features section accurately reflects active roadmap items.
- [ ] `.env.example` has `# passthrough: <reason>` on all non-config vars.
- [ ] `scripts/lint_docs.py` has Check 6 and Check 7 implemented and wired into `main()`.
- [ ] `python scripts/lint_docs.py` exits 0 (all 7 checks pass) from the repo root.
- [ ] `pytest tests/ -v --tb=short` passes with no failures.
- [ ] `ruff check src/` reports no new issues (no src changes, but confirm clean).
- [ ] `skills/docs-agent.md` formally defines `docs align-sync`.
- [ ] `docs/roadmap.md` updated with item 2.15.
- [ ] `docs/features/docs-align-sync.md` status changed to `Implemented` after merge to `main`.
- [ ] PR merged to `develop` first; CI green; then merged to `main`.
