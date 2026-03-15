# Multi-Provider Git Hosting (`REPO_PROVIDER`)

> Status: **Planned** | Priority: Medium | Last reviewed: 2026-03-15

Allow AgentGate to clone, sync, and interact with repositories hosted on GitLab, Bitbucket, and Azure DevOps — not only GitHub.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/multi-provider-git-hosting.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 8/10 | 2026-03-15 | OQ9/10/11/12/13/14/15 resolved in code samples. -1 OQ16 (git filter attack) accepted as pre-existing. -1 OQ11 REPO_USER per-provider format not enforced by Pydantic (runtime only). |
| GateSec  | 1 | 5/10 | 2026-03-15 | 2 blockers (OQ9, OQ10). See OQ9–OQ16 below. Commit `2db3bdd` |
| GateDocs | 1 | 7/10 | 2026-03-15 | 4 spec gaps fixed: missing `_AUTH_USERS` def, unused validation regexes, wrong test file for OQ14 test, inaccurate OQ16 mitigation. +`.env.example` added to Doc Updates. Commit `d73a0ce` |
| GateCode | 2 | — | 2026-03-15 | All GateDocs R1 fixes verified correct. Added 3 missing test cases to test plan: `test_bitbucket_user_re_rejects_invalid`, `test_azure_org_re_rejects_invalid` (OQ11 regex coverage), `test_configure_git_auth_token_with_special_chars` (OQ13 security test). |

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
7. **Auth** — New and renamed env vars: `REPO_PROVIDER`, `REPO_TOKEN` (replaces `GITHUB_REPO_TOKEN`), `REPO` (replaces `GITHUB_REPO`), `REPO_HOST`, `REPO_USER` (covers Bitbucket username and Azure org). See Config Variables section.
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

**Bitbucket** is relevant for Atlassian-centric shops. Auth requires a username in addition to the app password — the only provider with a two-part credential. `REPO_USER` provides the username; `REPO_TOKEN` the app password.

**Azure DevOps** is relevant for Microsoft-heavy enterprises. The repo URL structure is non-standard (`dev.azure.com/<org>/<project>/_git/<repo>`), requiring either user-supplied full URL or org/project/repo decomposition.

---

## Current Behaviour (as of v0.16.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Config | `src/config.py:26-31` (`GitHubConfig`) | 3 fields: `github_repo_token`, `github_repo`, `branch` — all GitHub-specific names || Clone | `src/repo.py:17` (`clone()`) | Builds `https://x-token-auth:<token>@github.com/<repo>` — hardcoded host |
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

### Axis 1 — Config naming: keep vs. rename

The user has one repository at a time. The existing `GITHUB_REPO_TOKEN`, `GITHUB_REPO`, and `GITHUB_REPO_TOKEN` fields are functionally identical for every provider — only the name is wrong. The pattern already used for AI backends applies directly here:

| AI backend pattern | Repo hosting pattern |
|---|---|
| `AI_CLI` selects backend | `REPO_PROVIDER` selects host |
| `AI_API_KEY` — generic key for all backends | `REPO_TOKEN` — generic token for all providers |
| `AI_MODEL` — generic model for all backends | `REPO` — generic `owner/repo` identifier for all providers |
| `AI_BASE_URL` — optional base URL override | `REPO_HOST` — optional self-hosted hostname override |
| _(no per-provider extra)_ | `REPO_USER` — optional username/org (Bitbucket + Azure only) |

#### Option A — Rename to agnostic names *(MAJOR bump)* *(recommended)*

Rename `GitHubConfig` → `RepoConfig`. Replace `GITHUB_REPO_TOKEN` → `REPO_TOKEN`, `GITHUB_REPO` → `REPO`. All `settings.github.*` refs become `settings.repo.*`. Introduce `REPO_PROVIDER` (default: `github`), `REPO_HOST`, and `REPO_USER` (replaces `BITBUCKET_USERNAME` and `AZURE_ORG` with a single generic field).

**Pros:**
- Consistent with the AI config pattern users already know
- One variable does what two (`BITBUCKET_USERNAME`, `AZURE_ORG`) did — fewer vars to document and remember
- Clean naming — no GitHub-specific words for generic concepts

**Cons:**
- Breaking change for existing deployments (must update compose/env files)
- Requires MAJOR version bump (`0.16.x` → `1.0.0`)
- Every test touching `settings.github` must be updated

#### Option B — Add `REPO_PROVIDER` without renaming *(MINOR bump)*

Keep `GitHubConfig` and `GITHUB_REPO_TOKEN` / `GITHUB_REPO` as-is. Add `REPO_PROVIDER`, `BITBUCKET_USERNAME`, and `AZURE_ORG` as optional fields.

**Pros:** Zero breaking change. MINOR bump only.

**Cons:** Field names stay misleading. Requires separate per-provider vars (`BITBUCKET_USERNAME`, `AZURE_ORG`) instead of the single generic `REPO_USER`. Inconsistent with the AI config pattern.

**Recommendation: Option A** — the rename is the right long-term decision. The project is pre-1.0 (`0.x`), making this the natural moment for a breaking change. The migration for existing users is a one-line env var rename.

---

### Axis 2 — Clone URL construction

Bot constructs the URL from `REPO_PROVIDER` + `REPO` + `REPO_TOKEN` (+ optional `REPO_HOST` and `REPO_USER`). For edge cases (self-hosted Bitbucket Server, Azure DevOps non-standard paths), a `REPO_CLONE_URL` escape hatch is available but not the primary path.

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
    "bitbucket": "https://{user}:{token}@{host}/{repo}.git",   # REPO_USER = username
    "azure":     "https://{user}:{token}@{host}/{user}/{repo}", # REPO_USER = org
}
```

---

### Axis 3 — Secret redaction for non-GitHub tokens

GitLab PATs have a detectable `glpat-` prefix. Bitbucket and Azure tokens have no unique prefix — covered by known-value matching (the token is always added to `SecretRedactor`'s candidate list). Add GitLab patterns to `_SECRET_PATTERNS`; document Bitbucket/Azure limitation.

---

## Recommended Solution

- **Axis 1**: Option A — rename to agnostic names, MAJOR bump, single `REPO_USER` replaces `BITBUCKET_USERNAME` + `AZURE_ORG`
- **Axis 2**: URL templates per provider + `REPO_CLONE_URL` escape hatch for edge cases
- **Axis 3**: Add GitLab PAT patterns; Bitbucket/Azure covered by known-value matching

### End-to-end flow

```
Startup:
  1. Settings.load() reads REPO_PROVIDER (default: "github")
  2. If REPO_CLONE_URL set → use verbatim (escape hatch)
     Else → build URL from template[provider] using REPO_TOKEN + REPO
            (+ REPO_USER for bitbucket username / azure org)
  3. repo.clone(url, branch) — gitpython handles any valid URL
  4. repo.configure_git_auth(token, host, user) — injects credentials for provider hostname
  5. commit-msg hook — extended with gitlab patterns + value-match for others

Runtime:
  gate sync  → git pull (unchanged)
  gate git   → git status (unchanged)
  gate diff  → git diff (unchanged, sanitize_git_ref still applies)
  gate info  → shows REPO_PROVIDER and REPO identifier

Redaction:
  SecretRedactor._SECRET_PATTERNS += glpat-* patterns
  known-value list includes settings.repo.repo_token → catches Bitbucket/Azure tokens
```

---

## Architecture Notes

- **`is_stateful` flag** — Not affected. Provider selection is purely a startup/clone concern.
- **`REPO_DIR` and `DB_PATH`** — always import from `src/config.py`; never hardcode `/repo` or `/data`.
- **`COPILOT_GITHUB_TOKEN` is separate** — This authenticates the Copilot CLI with GitHub, not the repo host. Even with `REPO_PROVIDER=gitlab`, users who use `AI_CLI=copilot` still need `COPILOT_GITHUB_TOKEN` pointing at GitHub. Same principle as `AI_API_KEY` and `COPILOT_GITHUB_TOKEN` already being separate concerns.
- **`gh` CLI** — Remains installed in the Docker image. Non-GitHub users will receive a "not authenticated" error if they call `gate run gh …`. A warning is shown in the startup ready message when `REPO_PROVIDER != github`.
- **Platform symmetry** — `gate info` changes in `src/bot.py` must be mirrored in `src/platform/slack.py`.
- **Auth guard** — All Telegram handlers remain decorated with `@_requires_auth`. No new handlers in this feature.
- **`configure_git_auth()`** — Currently sets `url.https://x-token-auth:<token>@github.com/.insteadOf https://github.com/`. Must be generalised. Signature changes to `configure_git_auth(token, host, user="x-token-auth")`.
- **`REPO_USER` semantics** — Bitbucket app passwords require `<username>:<app-password>`; `REPO_USER` is the username. For Azure, `REPO_USER` is the org prefix in `dev.azure.com/<org>/…`. For GitHub and GitLab, `REPO_USER` is empty (auth prefixes `x-token-auth` / `oauth2` are hardcoded per provider).
- **Azure URL structure** — `dev.azure.com/<org>/<project>/_git/<repo>`. The template covers standard paths when `REPO` contains `<project>/_git/<repo>`. For non-standard paths, `REPO_CLONE_URL` is the escape hatch.
- **`settings.github` → `settings.repo`** — All internal references must be updated. Grep targets before coding: `settings.github`, `GitHubConfig`, `github_repo_token`, `github_repo`.

---

## Config Variables

New and renamed vars (see Migration Guide in README):

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `REPO_PROVIDER` | `str` | `"github"` | Git hosting provider: `github`, `gitlab`, `bitbucket`, `azure`. |
| `REPO_TOKEN` | `str` | `""` | Repo host token / PAT / app-password. Replaces `GITHUB_REPO_TOKEN`. |
| `REPO` | `str` | `""` | Repo identifier (`owner/repo` for GitHub/GitLab/Bitbucket; `project/_git/repo` for Azure). Replaces `GITHUB_REPO`. |
| `BRANCH` | `str` | `"main"` | Branch name. Unchanged. |
| `REPO_HOST` | `str` | `""` | Override hostname for self-hosted instances (e.g., `gitlab.mycompany.com`). Like `AI_BASE_URL`. ⚠️ *GateSec: must validate — see OQ10.* |
| `REPO_USER` | `str` | `""` | Optional second credential. Bitbucket: username. Azure: org name. GitHub/GitLab: unused. ⚠️ *GateSec: must URL-encode — see OQ11.* |
| `REPO_CLONE_URL` | `str` | `""` | Escape hatch: full clone URL (token already embedded). Skips template construction. ⚠️ *GateSec: must whitelist HTTPS-only — see OQ9.* |

> `GITHUB_REPO_TOKEN` and `GITHUB_REPO` are **removed** in this MAJOR release. Existing deployments must rename these env vars. The migration is a one-line change per var.

---

## Implementation Steps

### Step 1 — `src/config.py`: rename `GitHubConfig` → `RepoConfig`

```python
class RepoConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    repo_token: str = ""                                # REPO_TOKEN — PAT / app-password / access token
    repo: str = ""                                      # REPO — owner/repo (or project/_git/repo for Azure)
    branch: str = "main"                                # BRANCH
    repo_provider: Literal["github", "gitlab", "bitbucket", "azure"] = "github"  # REPO_PROVIDER
    repo_host: str = Field("", env="REPO_HOST")         # self-hosted hostname (like AI_BASE_URL)
    repo_user: str = Field("", env="REPO_USER")         # username/org (Bitbucket/Azure only)
    repo_clone_url: str = Field("", env="REPO_CLONE_URL")  # escape hatch: full URL, skips template
```

Update `Settings` to reference `repo: RepoConfig` (was `github: GitHubConfig`). Update `Settings.load()` accordingly.

---

### Step 2 — `src/repo.py`: generalise clone URL and git auth

Add provider → default host mapping and URL templates:

```python
import re
import urllib.parse

_HOSTNAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9\-\.]*[A-Za-z0-9])?$')
_BITBUCKET_USER_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')
_AZURE_ORG_RE = re.compile(r'^[A-Za-z0-9\-]{1,64}$')

_DEFAULT_HOSTS = {
    "github":    "github.com",
    "gitlab":    "gitlab.com",
    "bitbucket": "bitbucket.org",
    "azure":     "dev.azure.com",
}

_CLONE_URL_TEMPLATES = {
    "github":    "https://x-token-auth:{token}@{host}/{repo}",
    "gitlab":    "https://oauth2:{token}@{host}/{repo}.git",
    "bitbucket": "https://{user}:{token}@{host}/{repo}.git",   # REPO_USER = username
    "azure":     "https://{user}:{token}@{host}/{user}/{repo}", # REPO_USER = org
}

# Default auth user prefix per provider (used by configure_git_auth).
# Bitbucket and Azure use REPO_USER as the actual username/org, so no prefix is needed.
_AUTH_USERS: dict[str, str] = {
    "github":    "x-token-auth",
    "gitlab":    "oauth2",
    "bitbucket": "",   # REPO_USER is the Bitbucket username; no additional prefix
    "azure":     "",   # REPO_USER is the Azure org; no additional prefix
}

def _build_clone_url(cfg) -> str:
    if cfg.repo_clone_url:
        # OQ9: HTTPS-only — reject file://, ssh://, git://, etc.
        parsed = urllib.parse.urlparse(cfg.repo_clone_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"REPO_CLONE_URL must use http:// or https://; got scheme {parsed.scheme!r}"
            )
        return cfg.repo_clone_url  # escape hatch — user owns the full URL

    # OQ10: REPO_HOST must be a bare hostname — no URL schemes, credentials, or path segments.
    if cfg.repo_host:
        if not _HOSTNAME_RE.match(cfg.repo_host) or any(
            c in cfg.repo_host for c in ("://", "@", "/")
        ):
            raise ValueError(
                f"REPO_HOST must be a bare hostname (e.g. gitlab.mycompany.com); "
                f"got {cfg.repo_host!r}"
            )

    host = cfg.repo_host or _DEFAULT_HOSTS.get(cfg.repo_provider, "github.com")
    tmpl = _CLONE_URL_TEMPLATES.get(cfg.repo_provider, _CLONE_URL_TEMPLATES["github"])
    # OQ11: per-provider format validation for REPO_USER before URL-encoding.
    if cfg.repo_provider == "bitbucket" and cfg.repo_user:
        if not _BITBUCKET_USER_RE.match(cfg.repo_user):
            raise ValueError(f"REPO_USER contains invalid Bitbucket username characters: {cfg.repo_user!r}")
    if cfg.repo_provider == "azure" and cfg.repo_user:
        if not _AZURE_ORG_RE.match(cfg.repo_user):
            raise ValueError(f"REPO_USER contains invalid Azure org name characters: {cfg.repo_user!r}")
    # OQ11: URL-encode token and user — special characters (@ / :) would break URL structure.
    safe_token = urllib.parse.quote(cfg.repo_token, safe="")
    safe_user  = urllib.parse.quote(cfg.repo_user,  safe="")
    return tmpl.format(
        token=safe_token,
        host=host,
        repo=cfg.repo.removeprefix(f"https://{host}/"),
        user=safe_user,
    )
```

Update `clone()` signature to accept `cfg` (the `RepoConfig` object) and call `_build_clone_url(cfg)`.

Update `configure_git_auth()`:

```python
async def configure_git_auth(token: str, host: str, user: str = "x-token-auth") -> None:
    # OQ13: URL-encode both user and token — Bitbucket/Azure tokens may contain
    # special characters that break git config URL parsing or cause truncation.
    safe_user  = urllib.parse.quote(user,  safe="")
    safe_token = urllib.parse.quote(token, safe="")
    url_prefix = f"https://{safe_user}:{safe_token}@{host}/"
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

Bitbucket and Azure tokens have no unique prefix — they are already covered by the known-value candidate list (`settings.repo.repo_token` is always added).

> *OQ14 fix:* When `REPO_CLONE_URL` is used, the token embedded in the URL is also collected:
> ```python
> from urllib.parse import urlparse
> parsed = urlparse(settings.repo.repo_clone_url)
> if parsed.password:
>     redactor.add_known_value(parsed.password)
> ```
> `parsed.password` extracts the `userinfo` password component, which is the token for all providers. This ensures Bitbucket/Azure tokens supplied via `REPO_CLONE_URL` (without a separate `REPO_TOKEN`) are redacted from AI responses and shell output.

---

### Step 4 — `src/main.py`: extend commit-msg hook patterns

Add GitLab patterns to `_PATTERNS` in `_install_commit_msg_hook()`:

```python
_PATTERNS = [
    # existing GitHub patterns …
    re.compile(r'glpat-[A-Za-z0-9_\-]{20,}'),
    re.compile(r'gldt-[A-Za-z0-9_\-]{20,}'),
    re.compile(r'glcbt-[A-Za-z0-9_\-]{20,}'),   # ⚠️ GateSec OQ15: was missing — must match redact.py
]
```

---

### Step 5 — `src/main.py`: startup validation

In `_validate_config()`, add provider-specific checks:

```python
if settings.repo.repo_provider not in {"github", "gitlab", "bitbucket", "azure"}:
    raise ValueError(f"Unknown REPO_PROVIDER: {settings.repo.repo_provider!r}")
if settings.repo.repo_provider in {"bitbucket", "azure"} and not settings.repo.repo_user:
    raise ValueError("REPO_USER is required when REPO_PROVIDER=bitbucket or azure")
# OQ9: REPO_CLONE_URL HTTPS-only (also checked in _build_clone_url; duplicated here for early failure)
if settings.repo.repo_clone_url:
    from urllib.parse import urlparse
    parsed = urlparse(settings.repo.repo_clone_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"REPO_CLONE_URL must use http:// or https://; got scheme {parsed.scheme!r}"
        )
# OQ10: REPO_HOST must be a bare hostname.
# Note: _HOSTNAME_RE is the same regex defined at module level in repo.py — import it
# rather than redefining it here to avoid drift between the two copies.
from src.repo import _HOSTNAME_RE
if settings.repo.repo_host and (
    not _HOSTNAME_RE.match(settings.repo.repo_host)
    or any(c in settings.repo.repo_host for c in ("://", "@", "/"))
):
    raise ValueError(
        f"REPO_HOST must be a bare hostname (e.g. gitlab.mycompany.com); "
        f"got {settings.repo.repo_host!r}"
    )
```

---

### Step 6 — `src/bot.py` and `src/platform/slack.py`: update `gate info`

Replace hardcoded "Repo" and "Branch" display with provider-aware version:

```python
provider = settings.repo.repo_provider.capitalize()
f"📁 {provider} Repo: `{settings.repo.repo}`\n"
f"🌿 Branch: `{settings.repo.branch}`\n"
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
await repo.clone(settings.repo)
host = settings.repo.repo_host or repo._DEFAULT_HOSTS.get(settings.repo.repo_provider, "github.com")
user = settings.repo.repo_user or _AUTH_USERS.get(settings.repo.repo_provider, "x-token-auth")
await repo.configure_git_auth(settings.repo.repo_token, host, user)
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/config.py` | **Edit** | Rename `GitHubConfig` → `RepoConfig`; rename fields `github_repo_token` → `repo_token`, `github_repo` → `repo`; add `repo_provider`, `repo_host`, `repo_user`, `repo_clone_url`; update `Settings` attribute `github` → `repo` |
| `src/repo.py` | **Edit** | Add `_DEFAULT_HOSTS`, `_AUTH_USERS`, `_CLONE_URL_TEMPLATES`, `_build_clone_url()`; generalise `clone()` and `configure_git_auth()` |
| `src/redact.py` | **Edit** | Add 3 GitLab token patterns; update `settings.github` → `settings.repo` reference |
| `src/main.py` | **Edit** | Add GitLab patterns to commit-msg hook; update provider validation; update `clone()` / `configure_git_auth()` call sites; add non-GitHub `gh` CLI warning; update all `settings.github` refs |
| `src/bot.py` | **Edit** | Update `gate info` provider display; update all `settings.github` refs |
| `src/platform/slack.py` | **Edit** | Mirror `gate info` provider display; update all `settings.github` refs |
| `tests/` | **Edit** | Update all `settings.github` → `settings.repo` and field renames across test helpers and assertions |
| `README.md` | **Edit** | New "Git Hosting Providers" section with migration guide; agnostic var table; `COPILOT_GITHUB_TOKEN` separation callout |
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
| `test_build_clone_url_bitbucket` | Bitbucket URL includes `REPO_USER` as username |
| `test_build_clone_url_azure` | Azure URL uses `REPO_USER` as org prefix and `dev.azure.com` |
| `test_build_clone_url_override` | `REPO_CLONE_URL` takes precedence over all templates |
| `test_configure_git_auth_gitlab_host` | Sets git config for `gitlab.com` instead of `github.com` |
| `test_configure_git_auth_repo_user` | Sets `<repo_user>:<token>` in URL for Bitbucket/Azure |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_repo_provider_default_github` | Default value is `"github"` |
| `test_repo_provider_unknown_raises` | Unknown provider raises `ValueError` in `_validate_config()` |
| `test_bitbucket_missing_repo_user_raises` | `REPO_PROVIDER=bitbucket` without `REPO_USER` raises `ValueError` |
| `test_azure_missing_repo_user_raises` | `REPO_PROVIDER=azure` without `REPO_USER` raises `ValueError` |

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

### `tests/unit/test_repo.py` additions *(GateSec R1)*

| Test | What it checks |
|------|----------------|
| `test_build_clone_url_rejects_ssh_protocol` | `REPO_CLONE_URL=ssh://…` raises `ValueError` (OQ9) |
| `test_build_clone_url_rejects_file_protocol` | `REPO_CLONE_URL=file:///…` raises `ValueError` (OQ9) |
| `test_repo_host_rejects_url_injection` | `REPO_HOST=evil.com/../../` is rejected (OQ10) |
| `test_repo_user_url_encoded` | `REPO_USER` with special chars is safely encoded (OQ11) |
| `test_bitbucket_user_re_rejects_invalid` | `_BITBUCKET_USER_RE` rejects usernames containing `@` or `/` (OQ11) |
| `test_azure_org_re_rejects_invalid` | `_AZURE_ORG_RE` rejects org names containing `@` or `/` (OQ11) |
| `test_configure_git_auth_token_with_special_chars` | Token containing `@` and `:` is URL-encoded in the git config URL; raw token must not appear verbatim in the configured URL (OQ13 security test) |

### `tests/unit/test_redact.py` additions *(GateSec R1)*

| Test | What it checks |
|------|----------------|
| `test_redact_gitlab_ci_build_token` | `glcbt-abc123…` is scrubbed from text |
| `test_repo_clone_url_token_redacted` | Token embedded in `REPO_CLONE_URL` is extracted and redacted from AI output (OQ14) — note: this tests `main.py` startup logic, not `repo.py`, so belongs here alongside other redaction tests |


---

## Documentation Updates

### `README.md`

Add a new **"Git Hosting Providers"** section with a provider matrix table, required env vars per provider, and a callout box clarifying that `COPILOT_GITHUB_TOKEN` is for the Copilot AI backend — not the repo host.

Add env var rows (agnostic pattern — same structure as AI config vars):

| Env var | Default | Description |
|---------|---------|-------------|
| `REPO_PROVIDER` | `github` | Git hosting provider: `github`, `gitlab`, `bitbucket`, or `azure`. |
| `REPO_TOKEN` | `""` | Token / PAT / app-password for the repo host. Replaces `GITHUB_REPO_TOKEN`. |
| `REPO` | `""` | Repo identifier (`owner/repo`). Replaces `GITHUB_REPO`. |
| `REPO_HOST` | _(provider default)_ | Override hostname for self-hosted instances. Like `AI_BASE_URL`. |
| `REPO_USER` | `""` | Username/org for providers that need it (Bitbucket username, Azure org). |
| `REPO_CLONE_URL` | `""` | Escape hatch: full clone URL (token already embedded), skips template construction. *Must use `https://` — `ssh://`, `file://`, `git://` are rejected at startup.* |

Add a **Migration Guide** callout:
> `GITHUB_REPO_TOKEN` → `REPO_TOKEN`, `GITHUB_REPO` → `REPO`. All other behaviour unchanged for GitHub users.

### `.env.example`

Update the lean `.env.example` to replace `GITHUB_REPO_TOKEN` and `GITHUB_REPO` with the new agnostic names. At minimum include `REPO_PROVIDER`, `REPO_TOKEN`, and `REPO`. Existing lean format (full list in README) is preserved.

```dotenv
REPO_PROVIDER=github
REPO=owner/repo
REPO_TOKEN=your-token-here
# For self-hosted or alternative providers, see README for REPO_HOST, REPO_USER, REPO_CLONE_URL
```

### `docs/roadmap.md`

Add:
```markdown
| 2.14 | Multi-provider git hosting — GitLab, Bitbucket, Azure DevOps | [→ features/multi-provider-git-hosting.md](features/multi-provider-git-hosting.md) |
```

---

## Version Bump

| This feature… | Bump |
|---------------|------|
| Renames `GITHUB_REPO_TOKEN` → `REPO_TOKEN` and `GITHUB_REPO` → `REPO`; renames `GitHubConfig` → `RepoConfig` | **MAJOR** |

**Expected bump**: `0.16.0` → `1.0.0`

---

## Edge Cases and Open Questions

1. **OQ1 — Azure repo URL structure** — Azure DevOps uses `dev.azure.com/<org>/<project>/_git/<repo>`. With `REPO_USER=<org>` and `REPO=<project>/_git/<repo>`, the URL template covers standard Azure paths. For non-standard layouts, `REPO_CLONE_URL` is the escape hatch. Full native Azure support (AZURE_PROJECT / AZURE_REPO decomposition) is a follow-up if needed.

2. **OQ2 — Self-hosted Bitbucket Server vs. Bitbucket Cloud** — Bitbucket Server (on-premise) uses HTTP access tokens (no username required). Proposed: `REPO_CLONE_URL` escape hatch; document Server limitation.

3. **OQ3 — Token rotation** — If the repo token is rotated while the container is running, `configure_git_auth()` is only called at startup. `gate sync` will fail with auth errors. Proposed answer: accepted limitation; `gate restart` resolves it. Document in README.

4. **OQ4 — `gate restart` interaction** — After restart, `clone()` is skipped (repo already exists at `REPO_DIR`). `configure_git_auth()` is re-run. Is the new token applied correctly? Proposed answer: yes — `configure_git_auth()` uses `git config --global … insteadOf` which overwrites on restart.

5. **OQ5 — Bitbucket app password vs. OAuth access token** — Bitbucket now supports OAuth 2.0 access tokens (no username required) in addition to app passwords. Proposed: support app passwords in v1 (most common); OAuth tokens via `REPO_CLONE_URL` escape hatch.

6. **OQ6 — `gh` CLI warning** — Should the `gh` CLI warning appear every startup, or only once (stored in `/data/`)? Proposed answer: every startup; it's a config-time warning, not a one-time notice.

7. **OQ7 — Copilot CLI + non-GitHub repo** — The Copilot CLI (`AI_CLI=copilot`) requires `COPILOT_GITHUB_TOKEN` pointing at GitHub. This is separate from the repo host. For non-GitHub repos, recommend `AI_CLI=codex` or `AI_CLI=api`.

8. **OQ8 — GitLab group-level access tokens** — GitLab group tokens have the same `glpat-` prefix as personal access tokens. Redaction patterns cover both — no separate case needed.

9. **OQ9 — `REPO_CLONE_URL` protocol whitelist** *(GateSec R1 — 🔴 BLOCKER → ✅ Resolved GateCode R1)* — The escape hatch would accept `file://`, `ssh://`, `git://` etc. — RCE / SSRF vectors. *Resolution:* `_build_clone_url()` and `_validate_config()` call `urllib.parse.urlparse()` and raise `ValueError` for any scheme other than `http`/`https`. See Step 2 and Step 5 code samples.

10. **OQ10 — `REPO_HOST` credential exfiltration via SSRF** *(GateSec R1 — 🔴 BLOCKER → ✅ Resolved GateCode R1)* — `REPO_TOKEN` would be sent to an attacker-controlled domain. *Resolution:* `_build_clone_url()` and `_validate_config()` validate `REPO_HOST` against `_HOSTNAME_RE` (`^[A-Za-z0-9]([A-Za-z0-9\-\.]*[A-Za-z0-9])?$`) and reject values containing `://`, `@`, or `/`. See Step 2 and Step 5 code samples.

11. **OQ11 — `REPO_USER` URL injection** *(GateSec R1 — 🟡 HIGH → ✅ Resolved GateCode R1)* — *Resolution:* `_build_clone_url()` calls `urllib.parse.quote(cfg.repo_user, safe="")` before interpolation. Per-provider format regexes (`_BITBUCKET_USER_RE`, `_AZURE_ORG_RE`) in Step 2 provide runtime format validation. Pydantic does not enforce format at load time; the runtime check is the primary gate.

12. **OQ12 — `repo_provider` must be `Literal`, not `str`** *(GateSec R1 — 🟡 MEDIUM → ✅ Resolved GateSec R1)* — Changed to `Literal["github", "gitlab", "bitbucket", "azure"]` in Step 1. Pydantic rejects unknown values at `Settings.load()`. `_validate_config()` retains an explicit check for a human-readable message.

13. **OQ13 — Token URL-encoding in `configure_git_auth()`** *(GateSec R1 — 🟡 MEDIUM → ✅ Resolved GateCode R1)* — *Resolution:* `configure_git_auth()` calls `urllib.parse.quote(token, safe="")` and `urllib.parse.quote(user, safe="")` before embedding in the git config URL. See Step 2 code sample.

14. **OQ14 — `REPO_CLONE_URL` token not collected by `SecretRedactor`** *(GateSec R1 — 🟡 HIGH → ✅ Resolved GateCode R1)* — *Resolution:* After HTTPS validation, `urlparse(settings.repo.repo_clone_url).password` is extracted and added to `SecretRedactor._known_values`. See Step 3 code sample.

15. **OQ15 — Commit-msg hook missing `glcbt-` pattern** *(GateSec R1 — 🟡 LOW → ✅ Resolved GateSec R1)* — `glcbt-` pattern added to Step 4 commit-msg hook list to stay in sync with Step 3 redact.py patterns.

16. **OQ16 — Git smudge/clean filter attacks from cloned repos** *(GateSec R1 — 🟡 MEDIUM, pre-existing — Accepted)* — Multi-provider support amplifies the existing risk from malicious `.gitattributes` smudge/clean filters. *Disposition:* accepted as pre-existing. Recommended mitigations: set `filter.<name>.clean` and `filter.<name>.smudge` to `cat` globally (neutralises registered filters), or set `GIT_CONFIG_NOSYSTEM=1` and supply a restricted global gitconfig that defines no filters. Note: `filter.*.required false` only prevents git from *failing* when a filter binary is absent — it does not prevent execution of filters that *are* present. Tracked as a follow-up hardening item (open GitHub issue).

---

## Acceptance Criteria

- [ ] All implementation steps above are complete.
- [ ] `pytest tests/ -v --tb=short` passes with no failures or errors.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] `README.md` updated: new "Git Hosting Providers" section, agnostic var table, migration guide, `COPILOT_GITHUB_TOKEN` separation callout.
- [ ] `docs/roadmap.md` entry added (and marked ✅ on merge to `main`).
- [ ] `docs/features/multi-provider-git-hosting.md` status changed to `Implemented` after merge.
- [ ] `VERSION` bumped to `1.0.0` on `develop` before merge PR to `main`.
- [ ] All new env vars have safe defaults that preserve existing GitHub behaviour for users who do not set `REPO_PROVIDER`.
- [ ] Feature works on both Telegram and Slack.
- [ ] Feature works with all AI backends; `copilot` + non-GitHub repo combination is documented (not blocked).
- [ ] OQ1–OQ8 resolved or explicitly accepted as known limitations with documentation.
- [ ] OQ9–OQ16 resolved or explicitly accepted (OQ9–OQ15 resolved in spec; OQ16 accepted as pre-existing with mitigation note).
- [ ] `gate info` correctly shows provider name on both platforms.
- [ ] GitLab PAT, deploy token, and CI build token patterns are redacted in AI responses and shell output.
- [ ] Bitbucket/Azure tokens are redacted by value-matching (verified by test).
- [ ] Commit-msg hook blocks GitLab PAT patterns in staged diffs.
- [ ] `REPO_CLONE_URL` validated as HTTPS-only (OQ9).
- [ ] `REPO_HOST` validated against hostname regex — no `://`, `@`, `/` (OQ10).
- [ ] `REPO_USER` URL-encoded and validated per provider (OQ11).
- [ ] `repo_provider` typed as `Literal["github","gitlab","bitbucket","azure"]` (OQ12 — resolved in spec).
- [ ] Token URL-encoded in `configure_git_auth()` (OQ13 — resolved in spec).
- [ ] `REPO_CLONE_URL` token extracted and added to `SecretRedactor` known-values (OQ14 — resolved in spec).
- [ ] Commit-msg hook includes `glcbt-` pattern (OQ15 — resolved in spec).
- [ ] PR merged to `develop` first; CI green; then merged to `main`.
