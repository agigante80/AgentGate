# Git SHA in ready-message version string (`GIT_SHA` / `IMAGE_TAG`)

> Status: **Implemented** (v0.17.0, commit `bbbe064`) | Priority: Medium | Last reviewed: 2026-03-14

When running a non-production build (local dev, CI preview, `develop` branch), the 🟢 Ready message now appends the short commit SHA to the version string — e.g. `v0.17.0-dev-f907318` — instead of the bare tag suffix `v0.17.0 :local-dev`.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/ready-msg-git-sha.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 10/10 | 2026-03-14 | Implemented |
| GateSec  | 1 | -/10 | - | Pending |
| GateDocs | 1 | 10/10 | 2026-03-14 | Authored |

**Status**: ✅ Implemented (v0.17.0)
**Approved**: Yes — implemented and shipped in commit `bbbe064`

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram + Slack). The ready message is built in `src/ready_msg.py` and consumed by both `src/main.py` and `src/platform/slack.py`.
2. **Backend** — AI backend agnostic; this touches only the startup message, not prompt handling.
3. **Stateful vs stateless** — Not applicable.
4. **Breaking change?** — No. The existing `IMAGE_TAG` env var is unchanged; `GIT_SHA` is new and optional. Old deployments that don't set it keep the existing format.
5. **New dependency?** — No. Git is already present in the Docker image (used by `src/runtime.py` for repo operations). `subprocess` is stdlib.
6. **Persistence** — None. SHA is read once at startup, held in memory, discarded on shutdown.
7. **Auth** — No new credentials required.
8. **Production guard** — The SHA is only shown when `IMAGE_TAG` is set to a value other than `"latest"`. When `IMAGE_TAG` is empty or `"latest"`, the format is unchanged.

---

## Problem Statement

1. **Ambiguous local-dev identity** — The ready message currently shows `v0.17.0 :local-dev` when `IMAGE_TAG=local-dev`. Operators running multiple local branches can't tell at a glance which exact commit is running.
2. **No commit traceability** — When debugging a behaviour difference between two `develop` snapshots, there is no quick way to correlate a running bot with a specific commit without `docker inspect` or SSH access.
3. **Inconsistent with standard versioning** — Pre-release version strings like `v0.17.0-dev-f907318` follow widely-understood semver pre-release conventions, making the label self-explanatory without extra context.

---

## Current Behaviour (as of v`0.17.0`)

| Location | Code | What it does |
|----------|------|--------------|
| `src/ready_msg.py:7-24` | `_resolve_sha(settings)` | Returns `GIT_SHA` env var if set, else runs `git rev-parse --short HEAD`; silent on error |
| `src/ready_msg.py:43-49` | `is_dev = bool(tag and tag != "latest")` / version-line logic | Non-`latest` tag + SHA → `v{ver}-dev-{sha}`; fallback to `:tag` suffix |
| `src/config.py:51` | `git_sha: str = ""` | `GIT_SHA` env var (new) |
| `src/config.py:50` | `image_tag: str = ""` | `IMAGE_TAG` env var (existing) |

Resulting ready-message line (local-dev with SHA):
```
🟢 AgentGate Ready — v0.17.0-dev-f907318
```

---

## Desired Behaviour

When `IMAGE_TAG` is set to any value other than `"latest"`, and a `GIT_SHA` (short hash, 7 chars) is available, the version line becomes:

```
🟢 AgentGate Ready — v0.17.0-dev-f907318
```

Rules:
- `IMAGE_TAG=latest` (or empty) → unchanged: `v0.17.0` (production format)
- `IMAGE_TAG=<anything else>` + SHA available → `v{version}-dev-{sha}`
- `IMAGE_TAG=<anything else>` + no SHA → `v{version} :{tag}` (fallback, unchanged)

The `:tag` backtick block is *replaced*, not appended, to keep the line short.

---

## Environment Variables

| Variable | Config field | Default | Description |
|----------|-------------|---------|-------------|
| `IMAGE_TAG` | `BotConfig.image_tag` | `""` | Existing. Non-`latest` value triggers SHA injection. |
| `GIT_SHA` | `BotConfig.git_sha` | `""` | New. Short commit hash (7 chars). Auto-detected from `git rev-parse --short HEAD` at startup if empty; falls back to empty string (no SHA shown). |

---

## Design

### SHA resolution order

1. `GIT_SHA` env var — takes priority (useful in CI Docker builds where git history may be shallow or absent).
2. `git rev-parse --short HEAD` in `REPO_DIR` — tried at startup if env var is empty; suppresses errors silently.
3. Empty string — falls back to existing `:tag` format.

### Version-line logic (in `src/ready_msg.py`)

```python
def _resolve_sha(settings: Settings) -> str:
    """Return short git SHA from env or git, or '' if unavailable."""
    if settings.bot.git_sha:
        return settings.bot.git_sha
    try:
        result = subprocess.run(
            ["git", "-C", REPO_DIR, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""

def build_ready_message(settings: Settings, version: str, prefix: str, use_slash: bool = True) -> str:
    tag = settings.bot.image_tag
    is_dev = bool(tag and tag != "latest")
    if is_dev:
        sha = _resolve_sha(settings)
        version_line = f"v{version}-dev-{sha}" if sha else f"v{version} `:{tag}`"
    else:
        version_line = f"v{version}" + (f" `:{tag}`" if tag else "")
    ...
```

---

## Files to Change

| File | Change |
|------|--------|
| `src/config.py` | Add `git_sha: str = ""` to `BotConfig` (env: `GIT_SHA`) |
| `src/ready_msg.py` | Add `_resolve_sha()` helper; update `build_ready_message()` version-line logic |
| `tests/unit/test_ready_msg.py` | Add/extend tests for the three cases: production, dev+sha, dev+no-sha |
| `README.md` | Add `GIT_SHA` row to the env var table under `IMAGE_TAG` |

No changes to `src/main.py`, `src/platform/slack.py`, `Dockerfile`, or `docker-compose.yml.example` — the existing `IMAGE_TAG` wiring is sufficient.

---

## Acceptance Criteria

- [x] `IMAGE_TAG=latest`, any `GIT_SHA` → version line is `v{version}` (unchanged)
- [x] `IMAGE_TAG` empty → version line is `v{version}` (unchanged)
- [x] `IMAGE_TAG=local-dev`, `GIT_SHA=f907318` → version line is `v{version}-dev-f907318`
- [x] `IMAGE_TAG=develop`, `GIT_SHA` not set, git available → version line is `v{version}-dev-{auto-detected-sha}`
- [x] `IMAGE_TAG=local-dev`, `GIT_SHA` not set, git unavailable → falls back to `v{version} :local-dev`
- [x] `GIT_SHA` env var overrides auto-detected git SHA
- [x] `_resolve_sha()` never raises; all errors are silently swallowed
- [x] Unit tests cover all five cases above
- [x] `README.md` env var table updated with `GIT_SHA` description

---

## Open Questions

_None at this time._
