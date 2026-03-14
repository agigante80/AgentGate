# Docker Image Tagging Strategy (`IMAGE_TAG` / CI-CD)

> Status: **Implemented** | Priority: High | Last reviewed: 2026-03-14

Formalise the Docker image tagging convention so users can pull predictable, well-named tags from `ghcr.io` for production (`latest` / `main`), development (`develop` / `development`), or pinned releases (`0.16.0`, `0.13.0-dev-f907318`).

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/docker-image-tagging.md`

| Reviewer | Round | Score | Date | Notes |
|----------|-------|-------|------|-------|
| GateCode | 1 | 9/10 | 2026-03-14 | Implementation matches spec exactly. Minor: open Q1 (pinned tag mutability) is a real risk on CI re-runs; Q4 (docker-compose example) worth addressing pre-approval. |
| GateSec  | 1 | 10/10 | 2026-03-14 | Authored |
| GateDocs | 1 | 9/10 | 2026-03-14 | Tag matrix and version-string table are clear and accurate. User Guide is comprehensive but missing a `docker login ghcr.io` note for registry pulls. OQ4 (`docker-compose.yml.example` registry snippet) should be resolved before approval; OQ1 (tag immutability) can be a follow-up CI task. |

**Status**: ⏳ Pending GateCode review
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — CI/CD pipeline only. No application code changes. Both platforms (Telegram + Slack) benefit equally because the image is platform-agnostic.
2. **Backend** — Not applicable. Tagging is independent of AI backend selection.
3. **Stateful vs stateless** — Not applicable.
4. **Breaking change?** — No. Existing tags (`latest`, `develop`) continue to resolve. New alias tags (`main`, `development`) are additive.
5. **New dependency?** — No. Uses existing `docker/build-push-action@v5` and GitHub Actions infrastructure.
6. **Persistence** — None. Tags are stored in the container registry (ghcr.io), not in-app.
7. **Auth** — No new credentials. Uses existing `GITHUB_TOKEN` with `packages: write` permission.
8. **Registry scope** — Single registry: `ghcr.io`. No DockerHub or ECR push.

---

## Problem Statement

1. **Unclear pull semantics** — Users need a simple mental model: _"`:latest` = stable production release, `:develop` = latest dev snapshot, `:0.16.0` = pinned version."_ Without a documented strategy, operators guess at tag names or hard-code SHAs.
2. **Missing alias tags** — Users may expect `:main` (mirrors the branch name) or `:development` (long-form alias) to work. Both should resolve to the same image as their short-form counterparts.
3. **No pinned dev versions** — Operators testing a specific `develop` commit need a tag like `0.13.0-dev-f907318` that survives the next `develop` push (unlike the rolling `:develop` tag).
4. **Multi-platform expectation** — Modern deployments span `amd64` and `arm64`. Every tag must be a multi-arch manifest, not a single-platform image.

---

## Tagging Scheme

### Tag matrix

| User pulls | Resolves to | Updated on | Example |
|------------|-------------|------------|---------|
| `:latest` | Latest stable release from `main` | Every `main` push (post-test) or `v*` tag push | `ghcr.io/agigante80/agentgate:latest` |
| `:main` | Same image as `:latest` | Same as above | `ghcr.io/agigante80/agentgate:main` |
| `:{semver}` | Pinned stable release | Once, on the `main` push that carries that `VERSION` | `ghcr.io/agigante80/agentgate:0.16.0` |
| `:develop` | Latest development snapshot | Every `develop` push (lint/test may be skipped) | `ghcr.io/agigante80/agentgate:develop` |
| `:development` | Same image as `:develop` | Same as above | `ghcr.io/agigante80/agentgate:development` |
| `:{semver}-dev-{sha}` | Pinned development snapshot | Once, on the `develop` push that carries that commit | `ghcr.io/agigante80/agentgate:0.17.0-dev-32089f2` |

### Version string construction

```
VERSION   = contents of /repo/VERSION (e.g. 0.17.0)
SHORT_SHA = git rev-parse --short HEAD (7 chars)

Branch              → Docker version string     → Rolling tags added
─────────────────────────────────────────────────────────────────────
main                → {VERSION}                 → latest, main
develop/development → {VERSION}-dev-{SHORT_SHA} → develop, development
refs/tags/v*        → {VERSION}                 → latest
other branches      → {VERSION}-{branch}-{SHA}  → (none)
```

### Multi-platform

All tags are multi-arch manifests built for:
- `linux/amd64`
- `linux/arm64`

---

## Current Implementation

The tagging strategy is fully implemented in `.github/workflows/ci-cd.yml`. No application code changes are needed.

### Version Generation job (ci-cd.yml)

```yaml
- name: 📝 Extract and build version string
  id: version
  run: |
    BASE_VERSION=$(cat VERSION | tr -d '[:space:]')
    SHORT_SHA=$(git rev-parse --short HEAD)

    if [[ "${{ github.ref }}" == "refs/heads/develop" || \
          "${{ github.ref }}" == "refs/heads/development" ]]; then
      VERSION="${BASE_VERSION}-dev-${SHORT_SHA}"
    elif [[ "${{ github.ref }}" == "refs/heads/main" ]]; then
      VERSION="${BASE_VERSION}"
    elif [[ "${{ github.ref }}" == refs/tags/v* ]]; then
      VERSION="${BASE_VERSION}"
    else
      BRANCH_NAME=$(echo "${{ github.ref_name }}" | sed 's/[^a-zA-Z0-9]/-/g')
      VERSION="${BASE_VERSION}-${BRANCH_NAME}-${SHORT_SHA}"
    fi

    DOCKER_VERSION="${VERSION//+/-}"
    # ... outputs: version, docker_version, is_release
```

### Docker tag generation (ci-cd.yml)

```yaml
- name: 🏷️ Generate Docker tags
  id: tags
  run: |
    DOCKER_VERSION="${{ needs.version.outputs.docker_version }}"
    IMAGE="${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}"

    TAGS="${IMAGE}:${DOCKER_VERSION}"

    if [[ "${{ github.ref }}" == "refs/heads/main" ]]; then
      TAGS="${TAGS},${IMAGE}:latest,${IMAGE}:main"
    elif [[ "${{ github.ref }}" == "refs/heads/develop" || \
            "${{ github.ref }}" == "refs/heads/development" ]]; then
      TAGS="${TAGS},${IMAGE}:develop,${IMAGE}:development"
    elif [[ "${{ github.ref }}" == refs/tags/v* ]]; then
      TAGS="${TAGS},${IMAGE}:latest"
    fi

    echo "tags=${TAGS}" >> $GITHUB_OUTPUT
```

### Build & push (ci-cd.yml)

```yaml
- name: 🏗️ Build and push
  uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64
    push: true
    tags: ${{ steps.tags.outputs.tags }}
    build-args: |
      VERSION=${{ needs.version.outputs.version }}
    labels: |
      org.opencontainers.image.version=${{ needs.version.outputs.version }}
      org.opencontainers.image.revision=${{ github.sha }}
```

### Publish gate conditions

| Branch | Lint must pass | Tests must pass | Publishes |
|--------|---------------|-----------------|-----------|
| `main` | ✅ Yes | ✅ Yes | Only if both pass |
| `develop` / `development` | ❌ No (advisory) | ❌ No (advisory) | Always (enables fast iteration) |
| `refs/tags/v*` | ✅ Yes | ✅ Yes | Only if both pass |
| Other branches | — | — | Never published |

---

## Security Considerations

1. **Registry authentication** — Uses `GITHUB_TOKEN` (automatically scoped to the repo) with `packages: write`. No long-lived PATs or external registry credentials stored in secrets.
2. **Tag mutability** — Rolling tags (`:latest`, `:main`, `:develop`, `:development`) are mutable by design. Pinned tags (`:0.16.0`, `:0.17.0-dev-32089f2`) should never be overwritten — the CI/CD pushes them once and subsequent pushes use a new SHA or version. _No enforcement mechanism exists today_ (see Open Questions §1).
3. **Supply chain** — Images include OCI labels (`org.opencontainers.image.version`, `revision`, `source`) for provenance tracing. No SBOM or Sigstore signing yet (see Open Questions §2).
4. **Develop branch gate** — `develop` publishes without requiring lint/test to pass. This is intentional for fast iteration but means `:develop` may contain broken code. Users should pin to a specific `{ver}-dev-{sha}` tag for stability.
5. **No user input in tags** — All tag components derive from `VERSION` file content, `git rev-parse`, and `github.ref` (GitHub-controlled). No PR title, commit message, or user-supplied string flows into tag names.

---

## User Guide

### Production deployment (stable)

```yaml
# docker-compose.yml
services:
  bot:
    image: ghcr.io/agigante80/agentgate:latest
    # or equivalently:
    # image: ghcr.io/agigante80/agentgate:main
```

Always tracks the latest stable release from `main`. Restart the container to pick up a new version.

### Development / preview deployment

```yaml
services:
  bot:
    image: ghcr.io/agigante80/agentgate:develop
    # or equivalently:
    # image: ghcr.io/agigante80/agentgate:development
```

Always tracks the latest `develop` snapshot. May contain in-progress features.

### Pinned version (reproducible)

```yaml
# Stable pin
services:
  bot:
    image: ghcr.io/agigante80/agentgate:0.16.0

# Dev pin (specific commit)
services:
  bot:
    image: ghcr.io/agigante80/agentgate:0.13.0-dev-f907318
```

Immutable — the image behind this tag never changes.

### Local build (no registry)

```yaml
services:
  bot:
    build: .
    environment:
      - IMAGE_TAG=local-dev
```

Sets `IMAGE_TAG` so the bot's ready message shows the non-production version format.

---

## Files Involved

| File | Role |
|------|------|
| `.github/workflows/ci-cd.yml` | Version generation, tag computation, multi-arch build & push |
| `VERSION` | Single source of truth for the base semver string |
| `Dockerfile` | Multi-stage build definition; `COPY VERSION .` bakes version into image |
| `docker-compose.yml.example` | Template showing `build: .` (local) — users replace with `image:` for registry pulls |
| `src/config.py` | `IMAGE_TAG` env var consumed by the bot at runtime (ready message) |
| `src/ready_msg.py` | Formats the version string displayed in the 🟢 Ready message |

---

## Config Variables

No new CI/CD env vars. The following `BotConfig` fields in `src/config.py` (lines 52–53) surface build provenance at runtime:

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `IMAGE_TAG` | `str` | `""` | Docker tag in use (e.g., `latest`, `develop`, `local-dev`). Set by docker-compose. Controls channel suffix in the 🟢 Ready message. |
| `GIT_SHA` | `str` | `""` | Short commit SHA (7 chars). Used by `src/ready_msg.py:_resolve_sha()` when `IMAGE_TAG` is non-production. Auto-resolved via `git rev-parse --short HEAD` if unset. |

> See `docs/features/ready-msg-git-sha.md` for the full rendering logic.

---

## Acceptance Criteria

- [x] `docker pull ghcr.io/agigante80/agentgate:latest` returns the latest `main` build
- [x] `docker pull ghcr.io/agigante80/agentgate:main` returns the same image as `:latest`
- [x] `docker pull ghcr.io/agigante80/agentgate:develop` returns the latest `develop` build
- [x] `docker pull ghcr.io/agigante80/agentgate:development` returns the same image as `:develop`
- [x] `docker pull ghcr.io/agigante80/agentgate:0.16.0` returns the pinned v0.16.0 stable release
- [x] `docker pull ghcr.io/agigante80/agentgate:0.13.0-dev-f907318` returns the pinned dev snapshot
- [x] All tags are multi-arch manifests (`linux/amd64` + `linux/arm64`)
- [x] `main` images only publish when lint + tests pass
- [x] `develop` images publish on every push (fast iteration)
- [x] Tag components contain no user-supplied input (no injection risk)
- [x] OCI metadata labels (`version`, `revision`, `source`) present on every image

---

## Open Questions

1. **Immutable pinned tags** — Should the CI/CD pipeline check whether a versioned tag (e.g. `:0.16.0`) already exists in the registry and skip the push to prevent accidental overwrites? Currently a re-run of the same `main` commit would silently overwrite. Low risk (same content), but violates strict immutability.
2. **Image signing / SBOM** — Should we add Sigstore/cosign signing or SBOM generation (`docker/build-push-action` supports `sbom: true`)? This would enable `cosign verify` for supply-chain validation. Not blocking but increasingly expected for open-source projects.
3. **Tag cleanup policy** — Old `{ver}-dev-{sha}` tags accumulate indefinitely in ghcr.io. Consider a scheduled workflow to prune dev tags older than N days, keeping only the latest M per minor version.
4. **`docker-compose.yml.example` update** — Should the example be updated to show an `image:` line (commented out) alongside `build: .` so users see how to pull from the registry? Currently it only demonstrates local builds.
