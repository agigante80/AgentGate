# Versioning Guide

AgentGate uses **Semantic Versioning** ([semver.org](https://semver.org)): `MAJOR.MINOR.PATCH`

---

## What each number means

```
  1   .   2   .   3
  │       │       └── PATCH — backwards-compatible bug fixes
  │       └────────── MINOR — new backwards-compatible functionality
  └────────────────── MAJOR — breaking changes
```

| Segment | Incremented when… | Resets when… |
|---------|-------------------|--------------|
| `MAJOR` | a change breaks backward compatibility (API removed, config key renamed, Docker volume layout changed, etc.) | — |
| `MINOR` | a new feature is added that does not break existing usage | `MAJOR` bumps → reset to `0` |
| `PATCH` | a bug fix, security patch, or dependency update that changes no public behaviour | `MINOR` bumps → reset to `0` |

---

## Decision guide

Ask yourself these questions in order:

1. **Will this break something for existing users?**
   - Renamed env variable, removed Telegram command, changed `/data` layout, dropped Python version support → **MAJOR**

2. **Does this add something new that users can opt into?**
   - New Telegram command, new AI backend, new config option with a default, new `/tahelp` entry → **MINOR**

3. **Does this only fix existing behaviour?**
   - Crash fix, wrong output corrected, dependency CVE patch, typo in a message → **PATCH**

---

## Practical examples for this project

| Change | Version |
|--------|---------|
| Fix ruff lint error | `PATCH` |
| Add `/tahelp` shows version number | `PATCH` |
| Add new AI backend (e.g. Gemini) | `MINOR` |
| New Telegram command `/tadiag` | `MINOR` |
| Rename `TG_BOT_TOKEN` env var | `MAJOR` |
| Drop support for `linux/amd64` Docker platform | `MAJOR` |
| Rewrite PTY session management | `MINOR` (if no API change) |

---

## How to bump the version

Edit the `VERSION` file in the repository root (a single line, no `v` prefix):

```
0.2.1
```

The CI pipeline reads this file and:
- On `develop` → builds image tagged `0.2.1-dev-<sha>` and `:develop`
- On `main` → builds image tagged `0.2.1`, `:latest`, `:main` and creates a GitHub Release

> **Rule:** the `VERSION` file is bumped on `develop` _before_ merging to `main`.  
> Never edit `VERSION` directly on `main`.

---

## Pre-release and dev builds

The pipeline appends context automatically — you never write these by hand:

| Context | Tag format | Example |
|---------|-----------|---------|
| `develop` branch | `X.Y.Z-dev-<sha>` | `0.2.1-dev-a1b2c3d` |
| `main` branch | `X.Y.Z` | `0.2.1` |
| `v*` git tag | `X.Y.Z` | `0.2.1` |

---

## When `MAJOR = 0`

While the project is in initial development (`0.Y.Z`), the rules above still apply
but with one relaxation: breaking changes may be shipped as `MINOR` bumps
(`0.1.0` → `0.2.0`) rather than requiring a `MAJOR` bump. Once the project
reaches a stable public API the version will be promoted to `1.0.0`.
