# Docs Align-Sync (`docs align-sync`)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-15

Keeps the four key user-facing reference files — `README.md`, `.env.example`, `docker-compose.yml.example`, and `scripts/lint_docs.py` — in sync with the actual source-of-truth (`src/config.py` and `docs/roadmap.md`).

*Authoritative contract:*

| File | Role |
|------|------|
| `README.md` | *Full* list of every env var, its default value, and a one-liner description. Single source of truth for operators. |
| `.env.example` | *Curated* — important vars only. Enough for a self-hoster to get started. Not exhaustive. |
| `docker-compose.yml.example` | *Mirrors `.env.example`* — the same important vars, in the compose `environment:` block. |

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/docs-align-sync.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 7/10 | 2026-03-15 | Two spec bugs fixed inline: (1) `_parse_env_example()` missing `re.match` guard for non-var tokens; (2) Check 7 direction inverted — must flag stale compose entries, not require all `.env.example` vars in compose. Checks 6+7 implemented in `lint_docs.py`; passthrough markers added to `.env.example`. |
| GateSec  | 1 | 7/10 | 2026-03-15 | 5 findings (F1–F5): F1 comment-line parsing, F2 passthrough injection, F3 no path traversal (clear), F4 substring false-positives, F5 completeness gap. Originally committed at `0d74f8a`; row overwritten by later edits. |
| GateCode | 2 | 8/10 | 2026-03-15 | Three bugs fixed from GateSec R1 findings: (F2) passthrough injection — a `# passthrough:` marker on a real config var now overrides to declared so stale detection is preserved; (F3) compose comment line matching — `_COMPOSE_VAR_RE` now skips `#`-prefixed lines, eliminating 9 false negatives from YAML example blocks; (F4) execution flow Step 5 direction mismatch corrected — Check 7 is stale-compose direction (not `.env.example → compose` coverage). Architecture Notes updated. All 7 checks pass, 538 tests green. |
| GateDocs | 1 | -/10 | - | Pending |
| GateCode | 3 | 8/10 | 2026-03-15 | Fixed Edge Case 3 (wrong direction — described coverage, not stale detection); fleshed out Step 6 with formal definition content spec for `skills/docs-agent.md`; corrected version bump note (0.18.x → current+1); tightened AC for `skills/docs-agent.md` definition. GateSec R1 F1 and F5 still unresolved — sec to verify scope on next pass. |
| GateSec  | 3 | 9/10 | 2026-03-15 | All 5 R1 findings resolved — verified against spec and implementation. F1 regex guard in place, F2 intersection check operational, F4 word-boundary regex + comment exclusion, F5 `all_known` properly used. One non-blocking nit (triple `extract_config_env_vars()` call). No new security concerns. |

| GateDocs | 3 | 9/10 | 2026-03-15 | Fixed `_parse_env_example` signature to accept `config_vars` param (eliminates 2 redundant `extract_config_env_vars()` calls per lint run); clarified version bump wording. |
| GateCode | 4 | 10/10 | 2026-03-15 | R3 Blocking Gap resolved: updated `_parse_env_example` in `scripts/lint_docs.py` to accept `config_vars: set[str]` as a parameter (removing internal `extract_config_env_vars()` call); both callers (`check_env_example_coverage`, `check_compose_coverage`) updated to pass the pre-extracted set. All 3 redundant `extract_config_env_vars()` calls per lint run now collapsed to 1. Linter still passes (17 specs clean). |
| GateSec  | 4 | 10/10 | 2026-03-15 | R3 perf nit resolved — `_parse_env_example` now accepts `config_vars` param; single `extract_config_env_vars()` call per lint run. Spec and implementation fully aligned. No security concerns. |
| GateDocs | 4 | -/10 | - | Pending |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

### Round 3 Blocking Gap (GateCode 8/10)

- `_parse_env_example` signature mismatch between spec and implementation: spec (updated in R3) now shows the function accepting `config_vars` as a parameter, but the implementation shipped with an internal `extract_config_env_vars()` call. GateCode should verify the live `scripts/lint_docs.py` matches the updated spec signature and, if not, apply the fix before scoring R4.

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
3. **README env var table incomplete** — `README.md` must be the *full* reference: every env var from `src/config.py`, its default value, and a one-liner description. Currently entries are missing or lack defaults.
4. **`.env.example` drift** — The file is meant to be a curated starter template (important vars only). Stale entries (vars removed from `src/config.py`) accumulate silently and confuse new users.
5. **`docker-compose.yml.example` drift** — Must mirror `.env.example` (same curated important vars). Additions/removals to `.env.example` are not propagated.
6. **No lint check enforces `.env.example` or `docker-compose.yml.example` coverage** — `scripts/lint_docs.py` currently has 5 checks; none cover these two files. Drift is only caught by a human.

---

## Current Behaviour (as of v`0.18.x`)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| `lint_docs.py` | `scripts/lint_docs.py` (checks 1–4) | Validates spec statuses, roadmap links, and cross-references. |
| `lint_docs.py` | `scripts/lint_docs.py:check_config_coverage()` | Check 5: every `src/config.py` env var must appear in `README.md`. Passes today. Does not verify defaults or descriptions. |
| `README.md` | `README.md:1–660` | Full document appears twice; second copy starts after the `## License` section. Env var table lacks defaults and per-var descriptions. |
| `.env.example` | `.env.example:1–38` | 13 variables; hand-maintained. Intended as a curated starter (important vars only), but no automated check removes stale entries. |
| `docker-compose.yml.example` | `docker-compose.yml.example:1–42` | References key vars; hand-maintained. No automated check that it mirrors `.env.example`. |
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
├─ Step 3: Refresh README.md env var table (full list)
│          For each var in src/config.py:
│            ensure README row exists with: var name | default | one-liner description
│          This is the ONLY place all vars must appear
│
├─ Step 4: Run lint check 6 — .env.example hygiene
│          .env.example is a CURATED list (important vars only — docs agent decides)
│          For each var in .env.example (non-passthrough):
│            if not in src/config.py → report stale entry (var was removed from code)
│          ⚠ Check 6 does NOT require every config.py var to appear in .env.example
│            (that is intentional — minor/internal vars are excluded from .env.example)
│
├─ Step 5: Run lint check 7 — docker-compose.yml.example stale detection
│          For each non-comment VAR= assignment in docker-compose.yml.example:
│            if not in src/config.py and not in .env.example (declared or passthrough) → report stale
│          ⚠ Check 7 does NOT require every .env.example var to appear in the compose file
│            (the compose file is also curated; direction is stale-compose, not coverage)
│
├─ Step 6: Apply fixes (docs agent edits files based on lint output)
│
└─ Step 7: Commit with message: "docs(align-sync): sync README, .env.example, docker-compose.yml.example"
```

---

## Architecture Notes

- **`lint_docs.py` is report-only** — it exits 0 or 1 and prints violations. It never modifies files. Fixes are applied by the docs agent after reading the lint output.
- **README is the single source of truth for env vars** — every var from `src/config.py` must appear in `README.md` with its default value and a one-liner description. This is enforced by Check 5 (existing) and extended in Step 3.
- **`.env.example` is curated, not exhaustive** — it contains only the vars a typical self-hoster *must* configure. Minor tunables (e.g. `STREAM_THROTTLE_SECS`) are intentionally omitted. The docs agent decides what is "important"; lint only enforces that no *stale* (removed) var remains.
- **`docker-compose.yml.example` mirrors `.env.example`** — not `src/config.py`. Both curated files stay in sync with each other. Check 7 is *stale-only*: it flags compose `VAR=` assignments (in non-comment lines) that are unknown to config.py or `.env.example` — it does not require every `.env.example` var to appear in compose.
- **`# passthrough:` marker safety** — a passthrough marker on a var that IS defined in `src/config.py` is overridden to declared, preventing accidental bypass of stale detection. The marker is only honoured for vars genuinely absent from config.py.

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

### Step 2 — Refresh `README.md` env var table (full list, with defaults + descriptions)

`README.md` must contain a table with *every* var from `src/config.py`, formatted as:

```markdown
| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM` | `telegram` | Which bot platform to use (`telegram` or `slack`). |
| `AI_CLI` | `copilot` | AI backend to use (`copilot`, `codex`, or `api`). |
...
```

The docs agent scans `src/config.py` for all field definitions and reconciles the README table — adding missing rows, updating stale defaults, and ensuring every row has a non-empty description. Check 5 (existing) enforces presence; this step also enforces defaults and descriptions.

---

### Step 3 — Add passthrough markers to `.env.example`

For every variable in `.env.example` that is intentionally absent from `src/config.py`, add an inline comment:

```bash
COPILOT_GITHUB_TOKEN=github_pat_xxxxxxxxxxxx   # passthrough: forwarded to copilot CLI subprocess
# REPO_HOST_PATH=/host/path                     # passthrough: Docker Compose bind-mount only
```

> Note: `.env.example` is a *curated* file — it contains only the vars a self-hoster needs to touch. Minor internal tunables (e.g. `STREAM_THROTTLE_SECS`, `HISTORY_TURNS`) are intentionally excluded. The docs agent maintains this curation editorially; lint only guards against stale entries.

---

### Step 4 — Extend `scripts/lint_docs.py` with Check 6

Add `check_env_example_coverage()` function:

```python
ENV_EXAMPLE_FILE = Path(".env.example")
_PASSTHROUGH_MARKER = "# passthrough:"

def _parse_env_example(config_vars: set[str]) -> tuple[set[str], set[str]]:
    """Return (declared_vars, passthrough_vars) from .env.example.

    Accepts the pre-extracted config_vars set to avoid redundant calls to
    extract_config_env_vars() — callers always have it available already.

    A passthrough marker on a genuine config var is treated as declared
    (guards against accidental marker on a real var bypassing stale detection).
    """
    declared, passthroughs = set(), set()
    if not ENV_EXAMPLE_FILE.is_file():
        return declared, passthroughs
    for line in ENV_EXAMPLE_FILE.read_text().splitlines():
        stripped = line.strip().lstrip("#").strip()
        if "=" not in stripped:
            continue
        var = stripped.split("=", 1)[0].strip()
        if not re.match(r'^[A-Z][A-Z0-9_]*$', var):
            continue
        if _PASSTHROUGH_MARKER in line and var not in config_vars:
            passthroughs.add(var)
        else:
            declared.add(var)
    return declared, passthroughs


def check_env_example_coverage(config_vars: set[str]) -> tuple[list[str], list[str]]:
    """Check 6: .env.example has no stale entries (vars no longer in config.py).

    NOTE: .env.example is intentionally a curated subset — not every config var
    must appear here. Only stale (removed) vars are flagged.
    """
    declared, passthroughs = _parse_env_example(config_vars)
    errors: list[str] = []

    # Stale entries: in .env.example (non-passthrough) but not in config.py
    for var in sorted(declared - config_vars):
        errors.append(
            f"[ENV EXAMPLE STALE] {var} is in .env.example but not in src/config.py "
            "(add '# passthrough: <reason>' if intentional)"
        )

    return errors, []
```

Wire into `main()` after check 5, sharing a single `extract_config_env_vars()` call with checks 6 and 7:

```python
config_vars = extract_config_env_vars()
env_errors, _ = check_env_example_coverage(config_vars)
errors.extend(env_errors)
```

---

### Step 5 — Extend `scripts/lint_docs.py` with Check 7

Add `check_compose_coverage()` function. Note the direction: Check 7 detects *stale* variable assignments in `docker-compose.yml.example` — variables that appear as `VAR=value` in *non-comment* lines of the compose file but are no longer in `src/config.py` or `.env.example`. Comment lines are explicitly skipped to avoid false positives from illustrative YAML comments. This is intentionally *not* a coverage check (not every `.env.example` var needs to appear in the compose file — the compose example is essentials-only).

```python
COMPOSE_EXAMPLE_FILE = Path("docker-compose.yml.example")
_COMPOSE_VAR_RE = re.compile(r'\b([A-Z][A-Z0-9_]{2,})=')

def check_compose_coverage(config_vars: set[str]) -> tuple[list[str], list[str]]:
    """Check 7: docker-compose.yml.example has no stale variable references.

    Parses ``VAR=`` assignments in non-comment lines of the compose file and
    flags any that are unrecognised — not in config_vars, not declared in
    .env.example, and not marked as a passthrough there.
    Comment lines are excluded to avoid false positives from YAML example blocks.
    """
    if not COMPOSE_EXAMPLE_FILE.is_file():
        return [], []
    declared, passthroughs = _parse_env_example(config_vars)
    all_known = declared | passthroughs | config_vars
    errors: set[str] = set()
    for line in COMPOSE_EXAMPLE_FILE.read_text().splitlines():
        if line.strip().startswith("#"):
            continue
        for m in _COMPOSE_VAR_RE.finditer(line):
            var = m.group(1)
            if var not in all_known:
                errors.add(
                    f"[COMPOSE STALE] {var} appears in docker-compose.yml.example "
                    "but is not in src/config.py or .env.example — "
                    "add a '# passthrough: <reason>' marker in .env.example if intentional"
                )
    return sorted(errors), []
```

Wire into `main()` after check 6, sharing the `config_vars` already extracted:

```python
config_vars = extract_config_env_vars()
env_errors, _ = check_env_example_coverage(config_vars)
errors.extend(env_errors)
compose_errors, _ = check_compose_coverage(config_vars)
errors.extend(compose_errors)
```

---

### Step 6 — Update `skills/docs-agent.md`

Replace the `*(To be defined…)*` placeholder under `### \`docs align-sync\`` with a formal definition alongside `docs roadmap-sync`. The definition must include:

- **When to run**: whenever any of `README.md`, `.env.example`, `docker-compose.yml.example`, or `src/config.py` changes.
- **Steps**: mirror the execution flow in §Recommended Solution (Steps 1–7 above).
- **Expected output**: `python scripts/lint_docs.py` exits 0; commit message `docs(align-sync): sync README, .env.example, docker-compose.yml.example`.
- **Passthrough guidance**: how to add `# passthrough: <reason>` to vars intentionally absent from `src/config.py`.

---

### Step 7 — Add `docs-align-sync` to `docs/roadmap.md`

Add row 2.15 to the roadmap table.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `README.md` | **Edit** | De-duplicate (merge best-of-both into ≈ 340–380 lines); add full env var table with defaults + one-liner descriptions |
| `.env.example` | **Edit** | Add `# passthrough: <reason>` markers to non-config vars; curate to important vars only |
| `docker-compose.yml.example` | **Edit** | Mirror `.env.example` important vars; remove any no-longer-present entries |
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
- Add (or update) the full env var reference table: every var from `src/config.py`, its default, and a one-liner description. This is the *only* file that must list all vars.

### `.env.example`

- Add `# passthrough: <reason>` to `COPILOT_GITHUB_TOKEN` and `REPO_HOST_PATH`.
- Keep only the most important vars — the ones a self-hoster must configure to get started. Remove or comment out internal tunables.

### `docker-compose.yml.example`

- Verify it mirrors the curated vars in `.env.example` (not the full `src/config.py` list).
- Add missing references; remove entries no longer in `.env.example`.

### `skills/docs-agent.md`

- Define `docs align-sync` command formally (alongside existing `docs roadmap-sync`).

---

## Version Bump

This feature fixes a README bug and adds lint checks with no user-visible config changes.

**Expected bump**: PATCH → next PATCH version after current `HEAD` on `main`. No user-visible config changes; this is a docs-tooling and lint improvement only.

---

## Roadmap Update

When complete, add to `docs/roadmap.md`:

```markdown
| 2.15 | ✅ Docs align-sync — README de-dup, .env.example & docker-compose coverage lint | [→ features/docs-align-sync.md](features/docs-align-sync.md) |
```

---

## GateSec R3 Findings (2026-03-15)

*Score: 9/10* — All 5 R1 findings verified resolved against both the spec and the live `scripts/lint_docs.py` implementation. No new security concerns.

### R1 Finding Resolution Status

| # | R1 Finding | Status | Resolution |
|---|-----------|--------|------------|
| F1 | Comment-line false-positive in `_parse_env_example()` | ✅ Resolved | `re.match(r'^[A-Z][A-Z0-9_]*$', var)` guard added (spec Step 4 + implementation). Non-var tokens with `=` are now skipped. |
| F2 | Passthrough marker trivially injectable | ✅ Resolved | `var not in config_vars` intersection check — a `# passthrough:` marker on a real config var is overridden to `declared`, preserving stale detection (spec Step 4 + Architecture Notes). |
| F3 | No path traversal / injection risk | ✅ Clear | Was already clean — `ENV_EXAMPLE_FILE` and `COMPOSE_EXAMPLE_FILE` are hardcoded `Path` constants. No user input influences paths. |
| F4 | Substring match false-positives in compose check | ✅ Resolved | `_COMPOSE_VAR_RE = re.compile(r'\b([A-Z][A-Z0-9_]{2,})=')` — proper regex extraction with word-boundary and 3-char minimum. Comment lines (`#`-prefixed) excluded from parsing. |
| F5 | Completeness gap (`all_known` unused) | ✅ Resolved | `all_known = declared | passthroughs | config_vars` is used in Check 7. Check 6 is correctly stale-only by design (curated list). Bidirectional concern was a misread of the original spec's intent. |

### New Observations (non-blocking)

- 🟢 *Performance nit*: `extract_config_env_vars()` is called 3× per lint run — once in `main()`, once inside each `_parse_env_example()` invocation from Check 6 and Check 7. Consider accepting `config_vars` as a parameter to `_parse_env_example()` during implementation to avoid redundant file reads. Not a security concern.
- 🟢 *Example tokens clean*: `.env.example` uses `github_pat_xxxxxxxxxxxx`, `ghp_xxxxxxxxxxxx`, `sk-xxxxxxxxxxxx` — no real credentials in example files.
- 🟢 *No new attack surface*: no runtime code changes, no new handlers, no subprocess calls, no user input paths. Pure docs-tooling.

---

## Edge Cases and Open Questions

1. **README merge conflict** — The two copies of `README.md` differ in subtle ways (feature bullet wording, Quick Start examples). The docs agent must diff them manually and choose the best content — this cannot be automated. Risk: low, since the merge is a one-time operation.

2. **"Important" vs "minor" config vars in `.env.example`** — *Resolved by design*: `.env.example` is a curated editorial list maintained by the docs agent, not an exhaustive mirror of `src/config.py`. Minor tunables (`STREAM_THROTTLE_SECS`, `HISTORY_TURNS`, etc.) are intentionally absent. Check 6 only flags *stale* entries (vars removed from `config.py`), not missing ones. `README.md` is the authoritative full list.

3. **`docker-compose.yml.example` scope** — Check 7 flags *stale* `VAR=` assignments in the compose file's non-comment lines — i.e. vars that no longer appear in `src/config.py` or `.env.example`. It does **not** require every `.env.example` var to appear in compose (the direction is stale-compose, not coverage). It does not validate YAML structure. Comment lines are explicitly excluded to avoid false positives from illustrative YAML examples.

4. **CI timing** — Checks 6 and 7 will fail CI if `.env.example` or `docker-compose.yml.example` goes stale after this feature ships. That is the desired behaviour, but the team should expect a first-run failure if the files are not fully updated before merging.

5. **`gate restart` interaction** — Not applicable; no runtime state.

6. **Slack thread scope** — Not applicable; this is a docs-agent-only command.

---

## Acceptance Criteria

- [ ] `README.md` contains no duplicate content; `wc -l README.md` is ≤ 400.
- [ ] `README.md` Features section accurately reflects active roadmap items.
- [ ] `README.md` env var table contains *every* var from `src/config.py` with its default value and a one-liner description.
- [ ] `.env.example` contains only the most important vars (curated starter set); internal tunables are absent.
- [ ] `.env.example` has `# passthrough: <reason>` on all non-config vars.
- [ ] `docker-compose.yml.example` mirrors exactly the vars in `.env.example` (curated list only, not all of `src/config.py`).
- [ ] `scripts/lint_docs.py` has Check 6 and Check 7 implemented and wired into `main()`.
- [ ] `python scripts/lint_docs.py` exits 0 (all 7 checks pass) from the repo root.
- [ ] `pytest tests/ -v --tb=short` passes with no failures.
- [ ] `ruff check src/` reports no new issues (no src changes, but confirm clean).
- [ ] `skills/docs-agent.md` `docs align-sync` definition includes: trigger conditions, execution steps, expected output format, and passthrough guidance.
- [ ] `docs/roadmap.md` updated with item 2.15.
- [ ] `docs/features/docs-align-sync.md` status changed to `Implemented` after merge to `main`.
- [ ] PR merged to `develop` first; CI green; then merged to `main`.
