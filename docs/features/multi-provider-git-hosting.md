# Multi-Provider Git Hosting (`REPO_PROVIDER`)

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-15

Allow AgentGate to clone, sync, and interact with repositories hosted on GitLab, Bitbucket, and Azure DevOps — not only GitHub.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/multi-provider-git-hosting.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | -/10 | - | Pending |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | 7/10 | 2026-03-15 | Strong design; 4 issues: (1) Azure template contradicts OQ1 escape-hatch deferral — template in Step 2 should be removed or flagged; (2) REPO_CLONE_URL table claims token auto-injection but code returns URL verbatim; (3) COPILOT_GITHUB_TOKEN separation not visually prominent enough in Architecture Notes; (4) Documentation Updates missing .env.example/.docker-compose.yml.example items and has wrong roadmap entry number (2.14 vs actual 2.15). |

**Status**: ⏳ Pending review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram + Slack). The repo hosting layer is platform-agnostic.
2. **Backend** — All AI backends (`copilot`, `codex`, `api`). However, `copilot` only works with GitHub-hosted repos; this must be documented, not enforced by code.
3. **Stateful vs stateless** — Not directly affected. Provider selection happens at clone time, before any backend interaction.
4. **Breaking change?** — `GitHubConfig` is renamed → `MAJOR` bump (`0.16.x` → `1.0.0`), OR we add `REPO_PROVIDER` without renaming (`MINOR` bump). See Axis 1 design decision.
5. **New dependency?** — None beyond what's already installed (`gitpython` is already a direct dep). Provider-specific API calls are not needed for clone/sync.
6. **Persistence** — No new DB table. Provider selection is a startup-time config value.
7. **Auth** — New env vars: `REPO_PROVIDER`, `REPO_TOKEN`, `REPO_URL`, `REPO_BRANCH`, and optionally `BITBUCKET_USERNAME` / `AZURE_ORG`. See Config Variables section.
8. **`COPILOT_GITHUB_TOKEN` dependency** — The Copilot CLI subprocess expects `COPILOT_GITHUB_TOKEN` in `os.environ`. This is unrelated to repo hosting and must continue to work even when `REPO_PROVIDER != github`. These are two distinct credentials: one authenticates with the repo host, the other authenticates the Copilot CLI with GitHub.
9. **Secret redaction** — Each provider has distinct token formats. The `SecretRedactor` and commit-msg hook must be extended to detect non-GitHub token patterns.
10. **Commit-msg hook** — Currently installs only GitHub PAT patterns. With multi-provider support, it must also block GitLab (`glpat-`), and document that Bitbucket / Azure tokens have no detectable prefix.

---

## Problem Statement

1. **GitHub lock-in** — `src/repo.py` hardcodes `https://github.com/` in clone and git-auth URLs (lines 17, 29). Teams using GitLab, Bitbucket, or Azure DevOps cannot deploy AgentGate without forking and patching the code.
2. **Token format assumptions** — `src/redact.py` detects only GitHub PAT patterns (`ghp_`, `gho_`, etc.). GitLab PATs (`glpat-`) and Azure PATs leak unredacted through AI responses and error messages.
3. **`gh` CLI is GitHub-only** — The Dockerfile installs `gh` and users may call it via `gate run gh …`. Non-GitHub users get a misleading tool they cannot authenticate with.
4. **`COPILOT_GITHUB_TOKEN` confusion** — Users on GitLab/Bitbucket still need to understand that `COPILOT_GITHUB_TOKEN` is for the Copilot AI backend — not for their repo host. Current documentation conflates the two.

---

## Competitor Analysis

### Top 3 GitHub Competitors

| # | Platform | Auth mechanism | Clone URL format | Token pattern |
|---|----------|---------------|------------------|---------------|
| 1 | **GitLab** | PAT / OAuth2 token | `https://oauth2:<token>@gitlab.com/<group>/<repo>.git` | `glpat-[A-Za-z0-9_-]{20,}` |
| 2 | **Bitbucket** | App password (username + secret) | `https://<username>:<app-password>@bitbucket.org/<workspace>/<repo>.git` | No unique prefix |
| 3 | **Azure DevOps** | PAT (Basic auth, base64-encoded) | `https://<org>:<pat>@dev.azure.com/<org>/<project>/_git/<repo>` | No unique prefix |

**GitLab** is the strongest candidate: it supports both cloud (`gitlab.com`) and self-hosted instances, has a well-known token format for redaction, and is the most common GitHub alternative for teams that self-host.

**Bitbucket** is relevant for Atlassian-centric shops. Auth requires a `BITBUCKET_USERNAME` in addition to the app password — the only provider with a two-part credential.

**Azure DevOps** is relevant for Microsoft-heavy enterprises. The repo URL structure is non-standard (`dev.azure.com/<org>/<project>/_git/<repo>`), requiring either user-supplied full URL or org/project/repo decomposition.

---

## Current Behaviour (as of v0.16.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Config | `src/config.py:26-31` (`GitHubConfig`) | 3 fields: `github_repo_token`, `github_repo`, `branch` — all GitHub-specific names |
| Clone | `src/repo.py:17` (`clone()`) | Builds `https://x-token-auth:<token>@github.com/<repo>` — hardcoded host |
| Git auth | `src/repo.py:29` (`configure_git_auth()`) | Sets `url.https://x-token-auth:<token>@github.com/.insteadOf https://github.com/` — hardcoded host |
| Redaction | `src/redact.py:18-30` | Detects 5 GitHub PAT patterns (`ghp_`, `gho_`, `ghs_`, `ghr_`, `github_pat_`) only |
| Redaction | `src/redact.py:61` | Adds `settings.github.github_repo_token` to known-values list |
| Commit hook | `src/main.py:132-136` | Blocks GitHub PAT patterns in committed diff/message |
| Bot info | `src/bot.py:446-447` | Displays `settings.github.github_repo` and `settings.github.branch` |
| Slack info | `src/platform/slack.py:779-780` | Same as Telegram |
| Dockerfile | Lines 10-17 | Installs `gh` CLI (GitHub-only tool) |

> **Key gap**: Every layer references `github.com` or GitHub-specific field names. Supporting a new provider requires changes in config, clone logic, git auth, secret redaction, commit hook, and info display — all currently tightly coupled to GitHub.

---

## Design Space

### Axis 1 — Config naming: rename vs. extend

#### Option A — Rename `GitHubConfig` → `RepoHostConfig` *(MAJOR bump)*

Replace all `settings.github.*` references with `settings.repo.*`. Introduce `REPO_PROVIDER` (default: `github`) to select provider. Rename `GITHUB_REPO_TOKEN` → `REPO_TOKEN`, `GITHUB_REPO` → `REPO_URL`, `BRANCH` → `REPO_BRANCH`.

**Pros:**
- Clean naming — no `github` in generic concepts
- Future providers slot in naturally

**Cons:**
- Breaking change for all existing deployments
- Requires MAJOR version bump (`0.16.x` → `1.0.0`)
- Every test touching `settings.github` must be updated

---

#### Option B — Add `REPO_PROVIDER` without renaming *(MINOR bump)* *(recommended)*

Keep `GitHubConfig` as-is. Add `repo_provider: str = "github"` to it. Add `BITBUCKET_USERNAME: str = ""` and `AZURE_ORG: str = ""` as optional fields. The `github_repo_token` field becomes the generic "token" regardless of provider. The `github_repo` field becomes the generic "repo identifier" (format varies by provider).

**Pros:**
- Zero breaking change — existing users set no new vars
- MINOR bump only
- All existing tests continue to pass without change

**Cons:**
- Field names (`github_repo_token`, `github_repo`) are slightly misleading for non-GitHub users
- Requires documentation to clarify field semantics for each provider

**Recommendation: Option B** — preserving backward compatibility for current deployments outweighs the cosmetic naming concern. Document field reuse clearly per provider.

---

### Axis 2 — Clone URL construction

#### Option A — User supplies full clone URL

Add `REPO_CLONE_URL` env var. If set, use it verbatim (after token injection). The bot does not construct the URL.

**Pros:** Works for any provider, including self-hosted GitLab/Bitbucket Server
**Cons:** Verbose for users; token injection into a user-supplied URL is complex

---

#### Option B — Bot constructs URL from provider + repo identifier *(recommended)*

For each known provider, define a URL template:

```python
_CLONE_URL_TEMPLATES = {
    "github":    "https://x-token-auth:{token}@github.com/{repo}",
    "gitlab":    "https://oauth2:{token}@gitlab.com/{repo}",
    "bitbucket": "https://{username}:{token}@bitbucket.org/{repo}",
    "azure":     "https://{org}:{token}@dev.azure.com/{org}/{repo}",
}
```

Self-hosted overrides use `REPO_HOST` (e.g., `gitlab.mycompany.com`).

**Pros:** Familiar config pattern; matches what users already set for GitHub
**Cons:** Azure URL structure is non-standard (org/project/_git/repo); `REPO_CLONE_URL` escape hatch needed for self-hosted edge cases

**Recommendation: Option B + `REPO_CLONE_URL` override escape hatch** for self-hosted/unusual cases.

---

### Axis 3 — GitLab / Azure self-hosted support

#### Option A — Cloud-only (gitlab.com, bitbucket.org, dev.azure.com)

Simpler. Covers the majority of users.

#### Option B — Add `REPO_HOST` override *(recommended)*

Optional `REPO_HOST` env var (default: empty = use provider default). When set, the URL template uses `REPO_HOST` instead of the provider's default hostname. Allows GitLab CE/EE on-premise.

**Recommendation: Option B** — minimal extra env var, unlocks enterprise self-hosted GitLab which is a primary use-case.

---

### Axis 4 — Secret redaction for non-GitHub tokens

#### Option A — Add patterns only for GitLab (detectable prefix)

GitLab PATs have `glpat-` prefix. Bitbucket and Azure tokens have no detectable prefix — only value-based redaction applies.

#### Option B — Add GitLab patterns + document Bitbucket/Azure limitations *(recommended)*

Extend `_SECRET_PATTERNS` with GitLab patterns. For Bitbucket/Azure, rely on known-value redaction (already in `SecretRedactor`) — the token value from config is always added to the candidate list.

**Recommendation: Option B** — pragmatic; GitLab prefix is detectable; others are caught by value-matching.

---

## Recommended Solution

- **Axis 1**: Option B — add `REPO_PROVIDER` to `GitHubConfig` (MINOR bump, zero breaking change)
- **Axis 2**: Option B + escape hatch — URL templates per provider + `REPO_CLONE_URL` override
- **Axis 3**: Option B — `REPO_HOST` optional override for self-hosted instances
- **Axis 4**: Option B — GitLab patterns added; Bitbucket/Azure covered by value-matching

### End-to-end flow

```
Startup:
  1. Settings.load() reads REPO_PROVIDER (default: "github")
  2. If REPO_CLONE_URL is set → use it directly (token injection applied)
     Else → build URL from template[provider] using GITHUB_REPO_TOKEN + GITHUB_REPO
            (+ BITBUCKET_USERNAME for bitbucket, AZURE_ORG for azure)
  3. repo.clone(url, branch) — unchanged internally (gitpython handles any URL)
  4. repo.configure_git_auth(token, host) — injects token for provider's hostname
  5. commit-msg hook — patched to detect gitlab patterns + value-match for others

Runtime:
  gate sync  → git pull (unchanged)
  gate git   → git status (unchanged)
  gate diff  → git diff (unchanged, sanitize_git_ref still applies)
  gate info  → shows REPO_PROVIDER and repo identifier

Redaction:
  SecretRedactor._SECRET_PATTERNS += glpat-* patterns
  known-value list already includes settings.github.github_repo_token → catches Bitbucket/Azure tokens
```

---

## Architecture Notes

> ⚠️ **`COPILOT_GITHUB_TOKEN` is not the same as your repo token.** `COPILOT_GITHUB_TOKEN` authenticates the Copilot CLI subprocess with GitHub — not with the repo host. Even if `REPO_PROVIDER=gitlab`, users running `AI_CLI=copilot` still need a valid `COPILOT_GITHUB_TOKEN` pointed at GitHub. These are two completely independent credentials. This distinction must appear prominently in README and in the startup ready message for non-GitHub providers.

- **`is_stateful` flag** — Not affected. Provider selection is purely a startup/clone concern.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode `/repo` or `/data`.
- **`gh` CLI** — Remains installed in the Docker image. Non-GitHub users will receive a "not authenticated" error if they call `gate run gh …`. We add a warning in the startup ready message when `REPO_PROVIDER != github`.
- **Platform symmetry** — `gate info` changes in `src/bot.py` must be mirrored in `src/platform/slack.py`.
- **Auth guard** — All Telegram handlers remain decorated with `@_requires_auth`. No new handlers in this feature.
- **`configure_git_auth()`** — Currently sets `url.https://x-token-auth:<token>@github.com/.insteadOf https://github.com/`. Must be generalised to use the provider's hostname. Signature changes to `configure_git_auth(token, host, username="")`.
- **Bitbucket two-part auth** — Bitbucket app passwords require `<username>:<app-password>`. `BITBUCKET_USERNAME` must be validated at startup (non-empty when `REPO_PROVIDER=bitbucket`).
- **Azure URL structure** — `dev.azure.com/<org>/<project>/_git/<repo>`. For v1, Azure is handled exclusively via `REPO_CLONE_URL` (see OQ1). Do _not_ rely on the `_CLONE_URL_TEMPLATES["azure"]` entry — it is retained only as a structural placeholder and is incomplete. Remove or annotate it with `# NOTE: Azure template construction is deferred — use REPO_CLONE_URL` before merging.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `REPO_PROVIDER` | `str` | `"github"` | Git hosting provider. One of: `github`, `gitlab`, `bitbucket`, `azure`. |
| `REPO_HOST` | `str` | `""` | Override hostname for self-hosted instances (e.g., `gitlab.mycompany.com`). Empty = use provider default. |
| `REPO_CLONE_URL` | `str` | `""` | Full clone URL override. Embed credentials directly in the URL — no token injection is applied. Takes precedence over template construction. *Required for Azure in v1.* |
| `BITBUCKET_USERNAME` | `str` | `""` | Required when `REPO_PROVIDER=bitbucket`. Bitbucket username for app-password auth. |
| `AZURE_ORG` | `str` | `""` | Required when `REPO_PROVIDER=azure`. Azure DevOps organisation name. |

Existing env vars that remain valid for all providers (semantics generalised):

| Env var | Generalised meaning |
|---------|---------------------|
| `GITHUB_REPO_TOKEN` | Repo host token / PAT / app-password (any provider) |
| `GITHUB_REPO` | Repo identifier: `owner/repo` (GitHub/GitLab/Bitbucket). Azure users: use `REPO_CLONE_URL` instead (see OQ1). |
| `BRANCH` | Branch name (unchanged) |

> **Naming note**: `GITHUB_REPO_TOKEN` and `GITHUB_REPO` retain their names for backward compatibility. Documentation must clearly state they apply to all providers.

---

## Implementation Steps

### Step 1 — `src/config.py`: extend `GitHubConfig`

```python
class GitHubConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    github_repo_token: str = ""
    github_repo: str = ""
    branch: str = "main"

    # Multi-provider additions:
    repo_provider: str = Field("github", env="REPO_PROVIDER")
    repo_host: str = Field("", env="REPO_HOST")         # self-hosted override
    repo_clone_url: str = Field("", env="REPO_CLONE_URL")  # full URL override
    bitbucket_username: str = Field("", env="BITBUCKET_USERNAME")
    azure_org: str = Field("", env="AZURE_ORG")
```

---

### Step 2 — `src/repo.py`: generalise clone URL and git auth

Add provider → default host mapping and URL templates:

```python
_DEFAULT_HOSTS = {
    "github":    "github.com",
    "gitlab":    "gitlab.com",
    "bitbucket": "bitbucket.org",
    "azure":     "dev.azure.com",
}

_CLONE_URL_TEMPLATES = {
    "github":    "https://x-token-auth:{token}@{host}/{repo}",
    "gitlab":    "https://oauth2:{token}@{host}/{repo}.git",
    "bitbucket": "https://{username}:{token}@{host}/{repo}.git",
    "azure":     "https://{org}:{token}@{host}/{org}/{repo}",
}

def _build_clone_url(cfg) -> str:
    if cfg.repo_clone_url:
        # Inject token into user-supplied URL if it contains a placeholder
        return cfg.repo_clone_url
    host = cfg.repo_host or _DEFAULT_HOSTS.get(cfg.repo_provider, "github.com")
    tmpl = _CLONE_URL_TEMPLATES.get(cfg.repo_provider, _CLONE_URL_TEMPLATES["github"])
    return tmpl.format(
        token=cfg.github_repo_token,
        host=host,
        repo=cfg.github_repo.removeprefix(f"https://{host}/"),
        username=cfg.bitbucket_username,
        org=cfg.azure_org,
    )
```

Update `clone()` signature to accept `cfg` (the `GitHubConfig` object) and call `_build_clone_url(cfg)`.

Update `configure_git_auth()`:

```python
async def configure_git_auth(token: str, host: str, username: str = "") -> None:
    auth_user = username or "x-token-auth"
    url_prefix = f"https://{auth_user}:{token}@{host}/"
    # git config --global url.<url_prefix>.insteadOf https://<host>/
```

---

### Step 3 — `src/redact.py`: add GitLab token patterns

```python
_SECRET_PATTERNS: list[re.Pattern] = [
    # existing GitHub patterns …
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),   # GitLab PAT
    re.compile(r"gldt-[A-Za-z0-9_\-]{20,}"),    # GitLab deploy token
    re.compile(r"glcbt-[A-Za-z0-9_\-]{20,}"),   # GitLab CI build token
]
```

Bitbucket and Azure tokens have no unique prefix — they are already covered by the known-value candidate list (`settings.github.github_repo_token` is always added).

---

### Step 4 — `src/main.py`: extend commit-msg hook patterns

Add GitLab patterns to `_PATTERNS` in `_install_commit_msg_hook()`:

```python
_PATTERNS = [
    # existing GitHub patterns …
    re.compile(r'glpat-[A-Za-z0-9_\-]{20,}'),
    re.compile(r'gldt-[A-Za-z0-9_\-]{20,}'),
]
```

---

### Step 5 — `src/main.py`: startup validation

In `_validate_config()`, add provider-specific checks:

```python
if settings.github.repo_provider == "bitbucket" and not settings.github.bitbucket_username:
    raise ValueError("BITBUCKET_USERNAME is required when REPO_PROVIDER=bitbucket")
if settings.github.repo_provider == "azure" and not settings.github.azure_org:
    raise ValueError("AZURE_ORG is required when REPO_PROVIDER=azure")
if settings.github.repo_provider not in {"github", "gitlab", "bitbucket", "azure"}:
    raise ValueError(f"Unknown REPO_PROVIDER: {settings.github.repo_provider!r}")
```

---

### Step 6 — `src/bot.py` and `src/platform/slack.py`: update `gate info`

Replace hardcoded "Repo" and "Branch" display with provider-aware version:

```python
provider = settings.github.repo_provider.capitalize()
f"📁 {provider} Repo: `{settings.github.github_repo}`\n"
f"🌿 Branch: `{settings.github.branch}`\n"
```

Also: when `repo_provider != "github"`, append a note in the ready message:

```
⚠️ REPO_PROVIDER=gitlab — the `gh` CLI is GitHub-only and cannot authenticate with this provider.
```

---

### Step 7 — `src/main.py`: update `clone()` call site

Update the call from:
```python
await repo.clone(token, settings.github.github_repo, settings.github.branch)
await repo.configure_git_auth(token)
```
to:
```python
await repo.clone(settings.github)
host = settings.github.repo_host or repo._DEFAULT_HOSTS.get(settings.github.repo_provider, "github.com")
await repo.configure_git_auth(settings.github.github_repo_token, host, settings.github.bitbucket_username)
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Add 5 fields to `GitHubConfig`: `repo_provider`, `repo_host`, `repo_clone_url`, `bitbucket_username`, `azure_org` |
| `src/repo.py` | **Edit** | Add `_DEFAULT_HOSTS`, `_CLONE_URL_TEMPLATES`, `_build_clone_url()`; generalise `clone()` and `configure_git_auth()` |
| `src/redact.py` | **Edit** | Add 3 GitLab token patterns to `_SECRET_PATTERNS` |
| `src/main.py` | **Edit** | Add GitLab patterns to commit-msg hook; add provider validation; update `clone()` / `configure_git_auth()` call sites; add non-GitHub `gh` CLI warning |
| `src/bot.py` | **Edit** | Update `gate info` provider display |
| `src/platform/slack.py` | **Edit** | Mirror `gate info` provider display |
| `README.md` | **Edit** | New "Git Hosting Providers" section; env var rows for new vars; note on `COPILOT_GITHUB_TOKEN` separation |
| `docs/features/multi-provider-git-hosting.md` | **Edit** | Mark status `Implemented` after merge |
| `docs/roadmap.md` | **Edit** | Add entry and mark done after merge |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `gitpython` | ✅ Already installed | Works with any git-compatible URL — no changes needed |
| `requests` / provider SDK | ❌ Not needed | No provider API calls required for clone/sync |

---

## Test Plan

### `tests/unit/test_repo.py` (new file)

| Test | What it checks |
|------|----------------|
| `test_build_clone_url_github` | GitHub URL uses `x-token-auth` and `github.com` |
| `test_build_clone_url_gitlab` | GitLab URL uses `oauth2` and `gitlab.com` |
| `test_build_clone_url_gitlab_self_hosted` | `REPO_HOST` overrides `gitlab.com` |
| `test_build_clone_url_bitbucket` | Bitbucket URL includes `BITBUCKET_USERNAME` |
| `test_build_clone_url_azure` | Azure URL uses org prefix and `dev.azure.com` |
| `test_build_clone_url_override` | `REPO_CLONE_URL` takes precedence over all templates |
| `test_configure_git_auth_gitlab_host` | Sets git config for `gitlab.com` instead of `github.com` |
| `test_configure_git_auth_bitbucket_username` | Sets `<username>:<token>` in URL for Bitbucket |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_repo_provider_default_github` | Default value is `"github"` |
| `test_repo_provider_unknown_raises` | Unknown provider raises `ValueError` in `_validate_config()` |
| `test_bitbucket_missing_username_raises` | `REPO_PROVIDER=bitbucket` without `BITBUCKET_USERNAME` raises `ValueError` |
| `test_azure_missing_org_raises` | `REPO_PROVIDER=azure` without `AZURE_ORG` raises `ValueError` |

### `tests/unit/test_redact.py` additions

| Test | What it checks |
|------|----------------|
| `test_redact_gitlab_pat` | `glpat-abc123…` is scrubbed from text |
| `test_redact_gitlab_deploy_token` | `gldt-abc123…` is scrubbed from text |
| `test_bitbucket_token_redacted_by_value` | Bitbucket app-password (no prefix) is caught by known-value matching |

### `tests/unit/test_main.py` additions

| Test | What it checks |
|------|----------------|
| `test_commit_hook_blocks_gitlab_pat` | Hook rejects commit with `glpat-` in staged diff |
| `test_gh_cli_warning_non_github` | Ready message includes `gh` CLI warning for non-GitHub providers |

---

## Documentation Updates

### `README.md`

Add a new **"Git Hosting Providers"** section with a provider matrix table, required env vars per provider, and a callout box clarifying that `COPILOT_GITHUB_TOKEN` is for the Copilot AI backend — not the repo host.

Add env var rows:

| Env var | Default | Description |
|---------|---------|-------------|
| `REPO_PROVIDER` | `github` | Git hosting provider: `github`, `gitlab`, `bitbucket`, or `azure`. |
| `REPO_HOST` | _(provider default)_ | Override hostname for self-hosted GitLab/Bitbucket instances. |
| `REPO_CLONE_URL` | `""` | Full clone URL override. When set, no token injection is applied — embed credentials directly. |
| `BITBUCKET_USERNAME` | `""` | Required when `REPO_PROVIDER=bitbucket`. |
| `AZURE_ORG` | `""` | Required when `REPO_PROVIDER=azure`. |

Update existing rows so descriptions reflect provider-agnostic meaning:
- `GITHUB_REPO_TOKEN` → "Repo host token / PAT / app-password (any provider)"
- `GITHUB_REPO` → "Repo identifier: `owner/repo` (GitHub / GitLab / Bitbucket); Azure users should set `REPO_CLONE_URL` instead"
- `BRANCH` → description unchanged (already generic)

### `.env.example`

Add commented-out entries for new vars:
```bash
# REPO_PROVIDER=github       # github | gitlab | bitbucket | azure
# REPO_HOST=                 # self-hosted override hostname
# REPO_CLONE_URL=            # full clone URL (Azure users: use this)
# BITBUCKET_USERNAME=        # required when REPO_PROVIDER=bitbucket
# AZURE_ORG=                 # required when REPO_PROVIDER=azure
```

### `docker-compose.yml.example`

No new entries required (lean format — refer to README for full variable list).

### `docs/roadmap.md`

Add:
```markdown
| 2.15 | Multi-provider git hosting — GitLab, Bitbucket, Azure DevOps | [→ features/multi-provider-git-hosting.md](features/multi-provider-git-hosting.md) |
```

---

## Version Bump

| This feature… | Bump |
|---------------|------|
| Adds new env vars with safe defaults, no renames or removals | **MINOR** |

**Expected bump**: `0.16.0` → `0.17.0`

---

## Edge Cases and Open Questions

1. **OQ1 — Azure repo URL structure** — Azure DevOps uses `dev.azure.com/<org>/<project>/_git/<repo>`. Should `GITHUB_REPO` contain `<project>/_git/<repo>` (with `AZURE_ORG` as org), or should we add dedicated `AZURE_PROJECT` and `AZURE_REPO` fields? Proposed answer: use `REPO_CLONE_URL` escape hatch for Azure; document in README. Full native Azure support is a follow-up. Needs decision before coding Step 2.

2. **OQ2 — Self-hosted Bitbucket Server vs. Bitbucket Cloud** — Bitbucket Server (on-premise) uses a different auth mechanism (HTTP access tokens, no `x-token-auth`). The URL template for Bitbucket Cloud may not work for Server. Proposed answer: `REPO_CLONE_URL` handles this; document Server limitation.

3. **OQ3 — Token rotation** — If the repo token is rotated while the container is running, `configure_git_auth()` is only called at startup. `gate sync` will fail with auth errors. Proposed answer: accepted limitation; `gate restart` resolves it. Document in README.

4. **OQ4 — `gate restart` interaction** — After restart, `clone()` is skipped (repo already exists at `REPO_DIR`). `configure_git_auth()` is re-run. Is the new token applied correctly? Proposed answer: yes — `configure_git_auth()` uses `git config --global … insteadOf` which overwrites on restart.

5. **OQ5 — Bitbucket app password vs. access token** — Bitbucket now supports OAuth 2.0 access tokens (no username required) in addition to app passwords. Should we support both? Proposed answer: support app passwords in v1 (most common); OAuth tokens via `REPO_CLONE_URL` escape hatch.

6. **OQ6 — `gh` CLI warning** — Should the `gh` CLI warning appear every startup, or only once (stored in `/data/`)? Proposed answer: every startup; it's a config-time warning, not a one-time notice.

7. **OQ7 — Copilot CLI + non-GitHub repo** — The Copilot CLI (`AI_CLI=copilot`) clones context from GitHub — it does not need the repo host to be GitHub. But the Copilot CLI may refuse to operate without a valid `COPILOT_GITHUB_TOKEN`. This is expected and documented. For non-GitHub repos, recommend `AI_CLI=codex` or `AI_CLI=api`.

8. **OQ8 — GitLab group-level access tokens** — GitLab group tokens have the same `glpat-` prefix as personal access tokens. Redaction patterns cover both — no separate case needed.

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` updated: new "Git Hosting Providers" section, env var rows, `COPILOT_GITHUB_TOKEN` separation callout.
- [ ] `docs/roadmap.md` entry added (and marked ✅ on merge to `main`).
- [ ] `docs/features/multi-provider-git-hosting.md` status changed to `Implemented` after merge.
- [ ] `VERSION` bumped to `0.17.0` on `develop` before merge PR to `main`.
- [ ] All new env vars have safe defaults that preserve existing GitHub behaviour for users who do not set them.
- [ ] Feature works on both Telegram and Slack.
- [ ] Feature works with all AI backends; `copilot` + non-GitHub repo combination is documented (not blocked).
- [ ] OQ1–OQ8 resolved or explicitly accepted as known limitations with documentation.
- [ ] `gate info` correctly shows provider name on both platforms.
- [ ] GitLab PAT, deploy token, and CI build token patterns are redacted in AI responses and shell output.
- [ ] Bitbucket/Azure tokens are redacted by value-matching (verified by test).
- [ ] Commit-msg hook blocks GitLab PAT patterns in staged diffs.
- [ ] PR merged to `develop` first; CI green; then merged to `main`.
