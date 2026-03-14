# Improved Security Scanning (CI/CD Pipeline)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-14

Reduce Trivy container-scan noise from ~1,500 alerts to actionable findings, and add
source-code security analysis (SAST) so real vulnerabilities in our Python code are
caught before merge.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/improved-security-scanning.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 9/10 | 2026-03-14 | Problem analysis airtight; YAML snippets verified against live workflow. Two additions: CodeQL scheduled-scan trigger + pip-audit SARIF syntax pre-validation. See OQ9 and OQ10. |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | 9/10 | 2026-03-14 | Comprehensive, accurate CI refs (lines verified). One inconsistency: Step 4 pip-audit snippet uses `\|\| true` (never fails), contradicting the Axis 4 recommendation of "fail on any". Fix before implementation. Roadmap entry added. |

**Status**: ⏳ In review (1/3 complete)
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

> Answer these before writing a single line of code. A wrong assumption at the start
> costs 10× more to fix than a clarification takes.

1. **Scope** — CI/CD pipeline only. No bot code, no platform code, no runtime changes.
2. **Backend** — N/A — this feature does not touch AI backends.
3. **Stateful vs stateless** — N/A.
4. **Breaking change?** — No. All changes are additive CI/CD workflow modifications.
   Existing `security-scan` job is preserved and improved in-place.
5. **New dependency?** — No new pip/npm packages. All tools run as GitHub Actions.
6. **Persistence** — No. Results are stored in GitHub's Security tab (SARIF uploads).
7. **Auth** — No new secrets required. `GITHUB_TOKEN` (automatic) provides
   `security-events: write` for SARIF uploads.
8. **Two tracks or one?** — This spec covers two complementary tracks that share the
   same CI job and Security tab destination. They should be implemented together to
   avoid duplicate workflow runs, but can be phased if needed.

---

## Problem Statement

1. **Alert volume is unmanageable** — The Security tab shows ~1,500 open alerts. This
   makes it impossible to spot real issues. Developers learn to ignore the tab entirely,
   defeating its purpose.

2. **Most alerts are irrelevant noise** — ~95% of alerts are CVEs in OS packages
   (`binutils`, `gcc`, `libc`), the Go 1.22 stdlib, and Node.js internals baked into
   the Docker image. These are not exploitable in our use case (a bot container, not a
   public-facing web server).

3. **Severity filter is broken** — The Trivy action's `severity: CRITICAL,HIGH` flag
   does not filter the SARIF output; it only affects the exit code. All severities
   (including LOW/MEDIUM) are uploaded to GitHub, contradicting the stated intent.

4. **Per-binary duplication inflates counts** — A single CVE in `binutils` generates 8
   separate alerts (one per sub-package: `binutils`, `binutils-common`,
   `binutils-x86-64-linux-gnu`, `libbinutils`, `libctf-nobfd0`, `libctf0`,
   `libgprofng0`, `libsframe1`). The ~1,500 alerts represent roughly ~700 unique CVEs.

5. **No source-code scanning** — Trivy scans the container image (OS packages, runtime
   binaries, language dependencies). It does *not* analyse our Python source for bugs,
   injection flaws, or logic errors. We have zero SAST coverage — a real vulnerability
   in `bot.py` or `executor.py` would not be flagged.

6. **No dependency-specific scanning** — Python dependency vulnerabilities (in
   `requirements.txt`) are only caught indirectly via the Docker layer scan. A dedicated
   `pip-audit` or equivalent would be faster, more precise, and catch issues before the
   Docker build step.

**Affected users**: all maintainers and contributors who look at the Security tab or
review Dependabot/security alerts. Self-hosters who fork the repo inherit the noisy
scan configuration.

---

## Current Behaviour (as of v0.17.0)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| CI/CD | `.github/workflows/ci-cd.yml:291–340` (`security-scan` job) | Builds Docker image locally, runs Trivy `image` scan, uploads SARIF to GitHub Security tab. |
| Trivy config | Inline in workflow YAML | `severity: CRITICAL,HIGH` (broken — does not filter SARIF). `exit-code: 0` (never fails the build). `format: sarif`. No `.trivy.yaml` config file. |
| Docker image | `Dockerfile` | Fat image: `python:3.12-slim` + `build-essential` + Node.js + Go 1.22.4 + `gh` CLI + Copilot CLI + Codex CLI. All of these contribute CVE alerts. |
| SAST | *(none)* | No CodeQL, Semgrep, or Bandit configuration exists in the repo. |
| Dependency audit | *(none)* | No `pip-audit`, `safety`, or `npm audit` step in CI. |
| SARIF upload | `github/codeql-action/upload-sarif@v4` | Used as a generic SARIF transport — not running CodeQL analysis itself. |

> **Key gap**: the pipeline scans the *container* but not the *code*. The container scan
> is unfiltered and noisy, burying any actionable finding. The code has zero static
> analysis coverage.

---

## Design Space

### Axis 1 — Reducing Trivy noise

#### Option A — Status quo *(baseline)*

Keep the current Trivy configuration unchanged.

**Pros:**
- No effort required.

**Cons:**
- ~1,500 unactionable alerts remain.
- Developers ignore the Security tab.
- Real issues (if any) are buried.

---

#### Option B — Filter SARIF + ignore unfixed *(recommended)*

1. Add `--ignore-unfixed` so CVEs with no available patch are excluded.
2. Use Trivy's `--severity CRITICAL,HIGH` as a *CLI argument* (not just `with:` input)
   to ensure the SARIF output is actually filtered.
3. Add a `.trivyignore` file for known false-positives specific to our image.

**Pros:**
- Dramatic reduction in alert count (estimated 80–90%).
- No Dockerfile changes required — fast to implement.
- `.trivyignore` is version-controlled and auditable.

**Cons:**
- Unfixed CVEs are hidden (acceptable — we can't act on them anyway).
- `.trivyignore` needs periodic review to avoid stale suppressions.

---

#### Option C — Multi-stage Docker build (slim image)

Restructure the Dockerfile to use multi-stage builds: install `build-essential` and Go
in a builder stage, copy only the compiled artefacts to a minimal final stage.

**Pros:**
- Eliminates hundreds of CVE sources at the root (no `gcc`, `binutils`, Go stdlib
  in final image).
- Smaller image size (faster pulls for users).

**Cons:**
- Significant Dockerfile refactor — higher effort, higher risk.
- Go and `build-essential` may be needed at runtime (e.g., `go build` in REPO_DIR).
- Should be its own feature spec (depends on runtime requirements analysis).

**Recommendation: Option B now, Option C as a follow-up feature.**
Option B is low-effort and immediately effective. Option C requires deeper analysis of
which tools are needed at runtime vs. build-time — it should be a separate spec.

---

### Axis 2 — SAST tool selection

#### Option A — CodeQL *(recommended)*

GitHub's native SAST engine. First-party integration with the Security tab, free for
public repos, built-in Python support.

**Pros:**
- Zero-cost for public repos on GitHub.
- Native Security tab integration (same UI as Trivy alerts, with code-flow views).
- Maintained by GitHub — automatic rule updates.
- Supports Python out of the box with high-quality queries.
- Auto-fix suggestions in PRs (Copilot Autofix).
- No external account or API key required.

**Cons:**
- Analysis can be slow (5–15 min for Python repos of this size).
- Custom rules use CodeQL's own query language (QL) — steep learning curve.
- Only runs on GitHub Actions (no local `pre-commit` equivalent).

---

#### Option B — Semgrep

Open-source SAST engine with a large community rule library and a SaaS dashboard.

**Pros:**
- Fast (~30s for a repo this size).
- Rules written in YAML — easy to create custom rules.
- Can run locally as a `pre-commit` hook.
- Large community rule library (>2,000 Python rules).

**Cons:**
- Free tier limits: 20,000 findings/month, limited dashboard retention.
- Requires a Semgrep account for the dashboard (or run OSS-only without it).
- SARIF upload to GitHub Security tab requires extra configuration.
- Another vendor dependency.

---

#### Option C — Bandit (Python-specific)

Python-only static analysis tool focused on common security issues.

**Pros:**
- Pure Python, easy to install (`pip install bandit`).
- Fast, focused on Python-specific issues (SQL injection, subprocess, exec, etc.).
- Can run as a `pre-commit` hook.

**Cons:**
- Python-only — won't catch issues in JS/shell scripts.
- Narrower rule set than CodeQL or Semgrep.
- Higher false-positive rate (no data-flow analysis).
- SARIF output requires `bandit -f sarif` (supported but less polished).

**Recommendation: Option A (CodeQL)** — native GitHub integration eliminates vendor
dependencies, the Security tab experience is seamless (same place as Trivy alerts), and
Copilot Autofix provides remediation suggestions for free. For a public GitHub repo,
CodeQL is the clear winner.

---

### Axis 3 — Python dependency scanning

#### Option A — No dedicated dependency scanning *(status quo)*

Rely on Trivy's container scan to catch dependency CVEs indirectly.

**Pros:**
- No additional CI step.

**Cons:**
- Indirect — Trivy scans installed packages in the Docker image, not
  `requirements.txt` directly. A vulnerability in a pinned-but-not-yet-installed dep
  won't be caught until the Docker image is built.
- Slower feedback loop (must wait for Docker build).

---

#### Option B — `pip-audit` in CI *(recommended)*

Add a lightweight CI step that runs `pip-audit -r requirements.txt` to check for
known vulnerabilities in Python dependencies.

**Pros:**
- Fast (~5s).
- Runs before Docker build — earlier feedback.
- Outputs SARIF for Security tab integration.
- Maintained by PyPA (Python Packaging Authority).

**Cons:**
- Only covers Python deps (not Node.js).
- Adds one more CI step.

---

#### Option C — Dependabot alerts only

Rely on GitHub's built-in Dependabot to flag dependency vulnerabilities.

**Pros:**
- Already enabled by default on public GitHub repos.
- Zero configuration.

**Cons:**
- Only creates alerts/PRs — does not block CI.
- Slower (daily scan, not per-push).

**Recommendation: Option B (`pip-audit`)** — fast, precise, and blocks on known
vulnerabilities before the Docker image is even built. Dependabot continues to run
as a complementary daily check.

---

### Axis 4 — CI failure policy

#### Option A — Report-only *(status quo)*

All security scans use `exit-code: 0` — they report findings but never fail the build.

**Pros:**
- Non-disruptive.
- No false-positive-induced CI failures.

**Cons:**
- No enforcement — vulnerabilities can be merged without review.

---

#### Option B — Fail on CRITICAL only *(recommended)*

- Trivy: `exit-code: 1` with `severity: CRITICAL` + `--ignore-unfixed`.
- CodeQL: use GitHub's default "Prevent merging" on CRITICAL/ERROR alerts.
- `pip-audit`: fail on any known vulnerability (they're all actionable).

**Pros:**
- Catches the worst issues before merge.
- `--ignore-unfixed` prevents false failures from unpatched CVEs.
- CRITICAL-only threshold avoids noise from disputed/low-impact findings.

**Cons:**
- A false-positive CRITICAL could block a merge (mitigated by `.trivyignore`).

**Recommendation: Option B** — report CRITICAL+HIGH, *fail only on CRITICAL with a fix
available*. This balances enforcement with developer experience.

---

## Recommended Solution

- **Axis 1**: Option B — filter Trivy SARIF output + `--ignore-unfixed` + `.trivyignore`
- **Axis 2**: Option A — CodeQL for SAST (native GitHub, free, seamless Security tab)
- **Axis 3**: Option B — `pip-audit` for Python dependency scanning
- **Axis 4**: Option B — fail on CRITICAL only (Trivy), default enforcement (CodeQL),
  fail on any (pip-audit)

### End-to-end CI flow (after implementation)

```
push / PR
  │
  ├─ [existing] version → lint + test (parallel)
  │
  ├─ [NEW] codeql-analysis          ← SAST scan of Python source
  │     └─ uploads SARIF → Security tab (Code scanning alerts)
  │
  ├─ [NEW] dependency-audit         ← pip-audit on requirements.txt
  │     └─ fails on known vuln; uploads SARIF → Security tab
  │
  ├─ [IMPROVED] security-scan       ← Trivy container scan (filtered)
  │     ├─ --ignore-unfixed
  │     ├─ --severity CRITICAL,HIGH (actually filters SARIF now)
  │     ├─ .trivyignore for false positives
  │     ├─ exit-code: 1 for CRITICAL only
  │     └─ uploads SARIF → Security tab
  │
  ├─ [existing] docker-publish
  └─ [existing] release
```

All three security jobs run in parallel after `lint` + `test`. Each uploads SARIF to
the same GitHub Security tab, so all findings (container, source, dependencies) are
visible in one place.

---

## Architecture Notes

> **Read before touching code.** These are non-obvious constraints or conventions.

- **CI-only feature** — No changes to `src/`, `tests/`, or runtime code. All changes
  are in `.github/workflows/` and repo-root config files.
- **SARIF convergence** — All three scanners (Trivy, CodeQL, pip-audit) upload SARIF
  to the same GitHub Security tab. GitHub deduplicates by tool name + rule ID.
  Different `tool.driver.name` values keep them separate in the UI.
- **CodeQL action versions** — Use `github/codeql-action/init@v4`,
  `github/codeql-action/analyze@v4`. These are already partially in the repo
  (the `upload-sarif` action is `@v4`).
- **Permissions** — CodeQL needs `security-events: write` (already granted to the
  `security-scan` job). The new jobs need the same permission.
- **Branch protection** — After implementation, consider enabling "Require status
  checks to pass" for the new jobs on `develop` and `main` branches.
- **`.trivyignore` format** — One CVE ID per line (e.g., `CVE-2024-12345`). Comments
  with `#`. Should include a comment explaining *why* each CVE is ignored.

---

## Config Variables

No new env vars or `src/config.py` changes. All configuration is in CI workflow YAML
and repo-root config files.

| File | Variable / setting | Value | Purpose |
|------|--------------------|-------|---------|
| `.github/workflows/ci-cd.yml` | Trivy `severity` | `CRITICAL,HIGH` | Filter SARIF output to actionable severities |
| `.github/workflows/ci-cd.yml` | Trivy `--ignore-unfixed` | `true` | Exclude CVEs with no available patch |
| `.github/workflows/ci-cd.yml` | Trivy `exit-code` | `1` (CRITICAL only) | Fail build on critical, fixable vulnerabilities |
| `.github/workflows/codeql.yml` | `languages` | `python` | Scan Python source code |
| `.trivyignore` | CVE IDs | *(per-image)* | Suppress known false-positives |

---

## Implementation Steps

### Step 1 — `.trivyignore`: create false-positive suppression file

Create `.trivyignore` at the repo root with known false-positives from the current
alert set. Include a header explaining the review process:

```
# .trivyignore — Trivy false-positive suppressions for AgentGate
# Review quarterly or when upgrading base image / toolchains.
# Format: one CVE ID per line. Lines starting with # are comments.
#
# Last reviewed: 2026-03-14

# build-essential / binutils — not exploitable in a bot container
# (these tools are only used at image build time for pip native extensions)
# CVE-YYYY-NNNNN
```

Populate with the top offenders from the current alert set (binutils, gcc, Go stdlib).

---

### Step 2 — `.github/workflows/ci-cd.yml`: fix Trivy SARIF filtering

Update the existing `security-scan` job:

```yaml
      - name: 🔒 Run Trivy vulnerability scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: agentgate:scan
          format: sarif
          output: trivy-results.sarif
          severity: CRITICAL,HIGH
          ignore-unfixed: true
          trivyignores: .trivyignore
          exit-code: '0'   # Phase 1: report only. Change to '1' after initial cleanup.
          limit-severities-for-sarif: true
```

Key changes:
- `ignore-unfixed: true` — excludes CVEs with no available patch.
- `trivyignores: .trivyignore` — suppresses known false-positives.
- `limit-severities-for-sarif: true` — ensures the `severity` filter actually applies
  to the SARIF output (not just the exit code). This is the fix for the broken filter.

---

### Step 3 — `.github/workflows/codeql.yml`: add SAST scanning

Create a new workflow file for CodeQL analysis:

```yaml
name: "CodeQL Analysis"

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  schedule:
    - cron: '0 6 * * 1'   # Weekly Monday 06:00 UTC

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    name: Analyze Python
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: 📥 Checkout repository
        uses: actions/checkout@v4

      - name: 🔧 Initialize CodeQL
        uses: github/codeql-action/init@v4
        with:
          languages: python
          queries: +security-and-quality
          # security-and-quality adds extra rules beyond the default
          # security-only set — catches code quality issues that could
          # become security problems.

      - name: 🔍 Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v4
        with:
          category: "/language:python"
```

Notes:
- Runs on push/PR to `main` and `develop`, plus a weekly schedule for new rule coverage.
- `queries: +security-and-quality` adds quality queries on top of default security queries.
- `category` distinguishes Python results from other languages if added later.

---

### Step 4 — `.github/workflows/ci-cd.yml`: add `pip-audit` dependency scanning

Add a new job to the existing CI/CD pipeline:

```yaml
  # --------------------------------------------------------------------------
  # Job: Dependency Audit (pip-audit)
  # --------------------------------------------------------------------------
  dependency-audit:
    name: Dependency Audit
    runs-on: ubuntu-latest
    timeout-minutes: 5
    needs: [version]
    permissions:
      contents: read
      security-events: write
    steps:
      - name: 📥 Checkout repository
        uses: actions/checkout@v4

      - name: 🐍 Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 📦 Install pip-audit
        run: pip install pip-audit

      - name: 🔍 Audit Python dependencies
        run: |
          pip-audit -r requirements.txt \
            --format sarif \
            --output pip-audit-results.sarif \
            --desc || true
          # `|| true` ensures we always upload results even if vulns are found

      - name: 📤 Upload pip-audit results to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v4
        if: always()
        with:
          sarif_file: pip-audit-results.sarif
          category: pip-audit

      - name: 📋 Dependency audit summary
        if: always()
        run: |
          echo "### 📦 Dependency Audit" >> $GITHUB_STEP_SUMMARY
          echo "- **Status**: ${{ job.status }}" >> $GITHUB_STEP_SUMMARY
          echo "- **Tool**: pip-audit" >> $GITHUB_STEP_SUMMARY
          echo "- **Scope**: requirements.txt" >> $GITHUB_STEP_SUMMARY
          echo "- **Results**: visible in the Security tab" >> $GITHUB_STEP_SUMMARY
```

---

### Step 5 — `.github/workflows/ci-cd.yml`: update summary job

Add the new `dependency-audit` job to the `needs:` list of the `summary` job so it
appears in the CI status overview:

```yaml
  summary:
    needs: [version, lint, test, docker-publish, security-scan, dependency-audit, release]
```

---

### Step 6 — Verify and tune

After the first CI run with all three scanners:

1. Review the Security tab — confirm alert count has dropped significantly.
2. Check for false positives from CodeQL — suppress with inline `# codeql: ignore`
   comments or a `codeql-config.yml` if needed.
3. Confirm `pip-audit` results are accurate — check for false positives from
   yanked/disputed advisories.
4. If Trivy alert count is acceptable, change `exit-code` from `'0'` to `'1'` to
   enforce the CRITICAL threshold.

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `.trivyignore` | **Create** | CVE suppression list for known false-positives |
| `.github/workflows/ci-cd.yml` | **Edit** | Fix Trivy SARIF filter (`limit-severities-for-sarif`, `ignore-unfixed`, `.trivyignore`). Add `dependency-audit` job. Update `summary` needs. |
| `.github/workflows/codeql.yml` | **Create** | CodeQL SAST workflow for Python source analysis |
| `README.md` | **Edit** | Add "Security Scanning" section describing the three-scanner setup |
| `docs/features/improved-security-scanning.md` | **Edit** | Mark status as `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Mark item as done; add follow-up for multi-stage Docker build |

---

## Dependencies

| Package / Action | Status | Notes |
|------------------|--------|-------|
| `aquasecurity/trivy-action@master` | ✅ Already used | Update configuration only. Consider pinning to a release tag. |
| `github/codeql-action/init@v4` | ✅ Available | Same action family as the existing `upload-sarif` step. |
| `github/codeql-action/analyze@v4` | ✅ Available | Standard GitHub-provided action. |
| `pip-audit` | ❌ Installed at CI runtime | `pip install pip-audit` in the workflow step. Not added to `requirements-dev.txt` (CI-only tool). |
| `actions/setup-python@v5` | ✅ Available | Standard GitHub-provided action. |

> No changes to `requirements.txt` or `requirements-dev.txt`. All tools are installed
> in ephemeral CI runners.

---

## Test Plan

This feature modifies CI workflows, not application code. Testing is done via CI run
validation, not `pytest`.

| Validation | What it checks |
|------------|----------------|
| CI run on `develop` after merge | All three security jobs complete successfully |
| Security tab alert count | Trivy alerts reduced from ~1,500 to < 100 |
| CodeQL findings | Python source alerts appear in Security tab with code-flow details |
| `pip-audit` findings | Dependency alerts appear (or clean bill of health) |
| False-positive review | No spurious CRITICAL/HIGH alerts in Trivy after `.trivyignore` |
| Existing tests unaffected | `pytest tests/ -v --tb=short` still passes (no test changes) |
| Summary job | `summary` job reflects all new jobs in its `needs` list |

---

## Documentation Updates

### `README.md`

Add a "Security Scanning" subsection under the CI/CD section:

```markdown
### 🔒 Security Scanning

The CI pipeline runs three complementary security scanners:

| Scanner | Scope | Finds |
|---------|-------|-------|
| **Trivy** | Docker image | CVEs in OS packages, runtimes, language deps |
| **CodeQL** | Python source | Injection flaws, logic bugs, unsafe patterns |
| **pip-audit** | `requirements.txt` | Known vulnerabilities in Python dependencies |

Results are visible in the [Security tab](../../security/code-scanning).
```

### `docs/roadmap.md`

- Mark "Improved Security Scanning" as done (✅).
- Add follow-up: "Multi-stage Docker build for minimal image" (links to a future spec).

---

## Version Bump

**No version bump required.** This feature changes only CI/CD workflows and
documentation — no runtime code is modified. The application version (`VERSION`) is
unchanged.

---

## Edge Cases and Open Questions

1. **Go stdlib alerts** — Go 1.22.4 is ~2 major versions behind (current: 1.24+). The
   Go stdlib alone accounts for hundreds of Trivy alerts. Should we bump Go as part of
   this feature, or track it separately?
   *Proposed answer*: track separately — a Go version bump may affect runtime behaviour
   and deserves its own testing.

2. **`limit-severities-for-sarif` availability** — This Trivy flag was added in
   trivy-action v0.18.0. Verify the `@master` tag includes it. If not, pin to a
   specific release that does.
   *Proposed answer*: pin `aquasecurity/trivy-action@0.28.0` (or latest stable) instead
   of `@master` for reproducibility.

3. **CodeQL analysis time** — CodeQL Python analysis typically takes 5–15 minutes. Is
   this acceptable for the CI pipeline? It runs in parallel with other jobs, so it
   shouldn't increase total wall-clock time unless it's on the critical path.
   *Proposed answer*: acceptable — it runs in parallel with `docker-publish` and
   `security-scan`, which are already 5–10 min.

4. **Existing ~1,500 alerts** — after fixing the SARIF filter + adding
   `--ignore-unfixed`, most existing alerts will auto-close on the next CI run (GitHub
   marks them "Fixed" when they disappear from the SARIF). Confirm this happens and
   there's no manual cleanup needed.

5. **CodeQL on PRs from forks** — CodeQL workflows triggered by `pull_request` from
   forks have limited permissions (no `security-events: write`). Use
   `pull_request_target` or accept that fork PRs won't get SAST results in the Security
   tab. Standard GitHub recommendation: use `pull_request` and rely on the base branch
   scan.

6. **`pip-audit` SARIF output** — Verify `pip-audit --format sarif` produces valid SARIF
   accepted by `upload-sarif`. Known to work as of pip-audit 2.7+.

7. **Trivy action pinning** — currently `@master` (floating). Should be pinned to a
   release tag for reproducibility. Dependabot can manage updates.

8. **Multi-stage Docker build** — the most effective long-term noise reduction. Should
   be a separate feature spec: analyse which tools (`go`, `gcc`, `make`) are needed at
   runtime vs build-time, then restructure the Dockerfile. *Not in scope for this spec.*

9. **CodeQL scheduled scan** — CodeQL's own documentation recommends adding a weekly
   scheduled scan on the default branch (in addition to push/PR triggers) to catch
   vulnerabilities introduced via dependency updates between pushes. The spec's
   `codeql.yml` YAML snippet omits this. Add a `schedule: - cron: '0 6 * * 1'`
   trigger to the CodeQL workflow.
   *Proposed answer*: add the weekly schedule to `codeql.yml` — low effort, best
   practice alignment.

10. **pip-audit SARIF command syntax** — the spec shows `pip-audit --format sarif` but
    the actual flag for pip-audit ≥ 2.7 is `pip-audit -r requirements.txt -f sarif -o
    pip-audit-results.sarif`. Pre-validate the exact syntax in the implementation step
    before merging — a broken CI command would silently skip the upload.
    *Proposed answer*: use `pip install pip-audit && pip-audit -r requirements.txt -f
    sarif -o pip-audit-results.sarif` and test against the latest pip-audit release.

---

## Acceptance Criteria

> The feature is **done** when ALL of the following are true.

- [ ] `.trivyignore` file exists with documented suppressions for known false-positives.
- [ ] Trivy SARIF output is filtered to CRITICAL+HIGH only (`limit-severities-for-sarif`).
- [ ] Trivy uses `--ignore-unfixed` to exclude CVEs with no available patch.
- [ ] Security tab alert count is reduced from ~1,500 to < 100 after the first CI run.
- [ ] CodeQL workflow (`.github/workflows/codeql.yml`) is created and runs on
      push/PR to `main` and `develop`.
- [ ] CodeQL Python findings appear in the Security tab.
- [ ] `pip-audit` job is added to CI/CD and runs on every push/PR.
- [ ] `pip-audit` SARIF results are uploaded to the Security tab.
- [ ] All three scanners (Trivy, CodeQL, pip-audit) coexist in the Security tab with
      distinct tool names.
- [ ] `summary` job's `needs` list includes `dependency-audit`.
- [ ] `README.md` documents the three-scanner setup.
- [ ] `docs/roadmap.md` entry is marked done (✅).
- [ ] Existing `pytest` suite passes unchanged (`pytest tests/ -v --tb=short`).
- [ ] `ruff check src/` reports no new linting issues.
- [ ] No new runtime dependencies are added.
- [ ] Trivy action is pinned to a release tag (not `@master`).
- [ ] PR is merged to `develop` first; CI is green; then merged to `main`.

---

## Future Work (out of scope)

These items are related but should be tracked as separate feature specs:

1. **Multi-stage Docker build** — restructure Dockerfile to remove `build-essential`,
   Go, and other build-time-only tools from the final image. Biggest single reduction
   in Trivy alert count.
2. **Go version bump** — update Go from 1.22.4 to latest stable. Eliminates hundreds
   of Go stdlib CVE alerts.
3. **Image signing and SBOM** — generate and publish Software Bill of Materials with
   each Docker image. Sign images with `cosign` for supply-chain verification.
4. **Secret scanning** — enable GitHub's native secret scanning or add a dedicated
   tool (TruffleHog, GitGuardian) for detecting leaked credentials in code/history.
5. **Branch protection rules** — require the new security jobs to pass before merging
   to `main` and `develop`.
