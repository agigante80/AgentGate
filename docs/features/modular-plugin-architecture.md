# Modular Plugin Architecture (pre-work for forks and cherry-pick)

> Status: **Planned** | Priority: High | Last reviewed: 2026-03-15

Refactor AgentGate's internals so that every major subsystem (platforms, AI backends,
commands, storage, services) is registered through a stable extension API rather than
wired by hand. Enables forks and downstream projects to cherry-pick only the subsystems
they need and to add new ones without modifying core files.

This is the pre-work milestone that must land *before* `remote-control-fork-project.md`
begins implementation.

---

## Team Review

> Managed automatically by the team review process — see `docs/guides/feature-review-process.md`.
> To start a review, ask any team member: `dev Please start a feature review of docs/features/modular-plugin-architecture.md`

| Reviewer | Round | Score | Date       | Notes |
|----------|-------|-------|------------|-------|
| GateCode | 1     | 7/10  | 2026-03-15 | 4 implementation bugs fixed: (1) `force=True` was silent — added `logger.warning()` on overwrite; (2) `_token` dataclass field breaks `__init__` kwarg and falsely claimed "not in repr()" — changed to `token: str = field(repr=False)`; (3) `AIConfig.secret_values()` used `self.codex_api_key` (flat, non-existent) — fixed to `self.codex.codex_api_key` (nested); (4) `_collect_secrets` used `__dict__`/`vars()` — changed to Pydantic v2 idiomatic `model_fields` iteration. OQ3 clarified: `commands/registry.py` defines the decorator; `bot.py` applies it — "shared definitions.py" option removed (circular import). |
| GateSec  | 1     | 6/10  | 2026-03-15 (9130578) | 8 OQs added (OQ9–OQ16): registry hijack, token exposure, InMemoryStorage bounds, SecretProvider gap, ImportError swallowing, detector injection, discovery mechanism. See inline `⚠️` annotations. |
| GateDocs | 1     | 6/10  | 2026-03-15 | 5 blockers fixed (OQ9 code/test mismatch, OQ10/11 code/criteria mismatch, `vars(settings)` Pydantic incompatibility, `AIConfig.codex` wrong reference, InMemoryStorage code/test desync). 6 gaps addressed (`.env.example` added, OQ14 test, OQ15 AC, COMMANDS dedup note, OQ16 comment corrected, `remote-control-fork-project.md` added to Files table). |
| GateCode | 3     | 9/10  | 2026-03-15 | GateDocs R2 blockers verified ✅. One residual gap fixed: Step 5b code sample called `_module_file_exists()` without an import — would be a `NameError` at runtime. Fix: (1) extracted `_module_file_exists()` from `factory.py` inline definition into a new `src/_loader.py` module; (2) updated both Step 5a (`factory.py`) and Step 5b (`main.py`) samples to `from src._loader import _module_file_exists`; (3) extraction note updated to reference `src/_loader.py` concretely; (4) `src/_loader.py` added to Files to Create/Change; (5) two unit tests added for `_module_file_exists` in isolation. Step 4a OQ18 duplicate-check verified correct as-written. |
| GateSec  | 2     | 8/10  | 2026-03-15 (cd13e43) | R1 OQs resolved: OQ9 (registry hijack → ValueError default), OQ11 (NullRepoService standalone), OQ12 (InMemoryStorage bounded), OQ14 (accepted + logged), OQ15 (find_spec pattern), OQ16 (hardcoded list). OQ10 partially resolved (repr=False). OQ13 mitigated (test coverage). 2 new: OQ17 (platform import inconsistency with Step 5a), OQ18 (COMMANDS list no uniqueness check). |
| GateDocs | 2     | 7/10  | 2026-03-15 | 2 blockers fixed: (1) Step 5b `main.py` sample replaced bare `try/except ImportError: pass` with `_load_platforms()` matching the OQ15-compliant pattern from Step 5a — OQ17 resolved; (2) `register_command()` in Step 4a now raises `ValueError` on duplicate `name` — OQ18 resolved. 4 gaps addressed: test rows added for OQ17 and OQ18, `.github/copilot-instructions.md` added to Files table, duplicate GateSec security-additions test rows consolidated. |

| GateDocs | 3     | 8/10  | 2026-03-15 | GateCode R3 verified ✅. 2 stale wording gaps fixed: (1) Step 5b extraction note read "must be extracted" — GateCode R3 already completed the extraction to `src/_loader.py`; updated to past tense; (2) OQ17 still listed `src/registry.py` as an alternative — settled to `src/_loader.py` to match Files table and code samples. Spec is implementation-ready: all blockers resolved, all OQs documented (OQ10 accepted with repr=False, OQ13 mitigated with test coverage). |

**Status**: ⏳ In review — round 3
**Approved**: No — requires all scores ≥ 9/10 in the same round

---

## ⚠️ Prerequisite Questions

1. **Scope** — Both platforms (Telegram + Slack). The refactor touches every layer that
   both share.
2. **Breaking change?** — No. All existing env vars, commands, and Docker volume layout
   are preserved. Internal APIs change significantly; external API (env vars, commands,
   behaviour) does not. → **MINOR** bump.
3. **New dependency?** — No new runtime deps. Uses Python's built-in `importlib.metadata`
   entry-points for the optional third-party plugin discovery path; that module ships with
   Python ≥ 3.9.
4. **Fork compatibility** — A fork must be able to delete entire directories (e.g.,
   `src/platform/slack.py`, `src/ai/copilot.py`) and still boot, provided the deleted
   subsystem is not selected via env vars. No `ImportError` on unselected paths.
5. **Refactor order** — Each step must leave the test suite fully green. No "big bang"
   rewrites. Five independent milestones (see Implementation Steps) each mergeable on their
   own.
6. **Persistence** — No new DB tables. This is a code-organisation refactor.
7. **Auth** — No new secrets. Existing auth guards are preserved and moved, not changed.
8. **Performance** — Registry lookups happen once at startup; no hot-path overhead.

---

## Problem Statement

1. **Forks must edit core files to add or remove a subsystem.** `src/ai/factory.py` is an
   `if/elif` chain that lists every backend by name; adding `AI_CLI=gemini` requires editing
   it. `src/main.py` has a hard `if settings.platform == "slack"` branch; adding a Discord
   adapter requires editing it. A fork that removes Telegram must still carry `src/bot.py`
   and `python-telegram-bot`.

2. **Commands are duplicated between platforms.** The `gate run`, `gate sync`, `gate git`, …
   dispatch tables exist independently in `src/bot.py` (~120 lines) and
   `src/platform/slack.py` (~180 lines). A new command must be added in both files, and
   they drift over time (Slack has `init`, `info`; Telegram's implementation differs in
   subtle ways).

3. **`SecretRedactor` is tightly coupled to `Settings`.** `_collect_secrets()` hand-lists
   every field that might hold a secret (`settings.telegram.bot_token`,
   `settings.slack.slack_bot_token`, …). Adding a new secret-bearing config field requires
   a corresponding edit in `redact.py`, which is easy to forget (it caused the v0.13.0
   `CODEX_API_KEY` leak).

4. **Services are imported directly by handlers.** `src/bot.py` and `src/platform/slack.py`
   do `from src import executor, repo` at the module level. There is no way for a fork to
   swap `repo` for a different git provider without patching the platform files. Unit tests
   must monkeypatch global imports.

5. **`src/runtime.py` hardcodes the detector list.** The list of `(manifest_file, install_cmd)`
   pairs is a module-level constant. A fork targeting a different project type (e.g., Rust
   with `Cargo.toml`) must edit `runtime.py`.

6. **`main.py` is a startup monolith.** It instantiates concrete classes
   (`SQLiteStorage`, `SQLiteAuditLog`) directly. A fork wanting an in-memory storage or
   a remote audit backend must patch `main.py`.

---

## Current Behaviour (as of v0.18.x)

| Layer | Location | Current behaviour |
|-------|----------|-------------------|
| Platform selection | `src/main.py:startup()` | Hard `if/else` on `settings.platform` — imports and starts `SlackBot` or `build_app` |
| AI backend selection | `src/ai/factory.py:create_backend()` | `if/elif` chain on `ai.ai_cli` literal — imports concrete class per branch |
| Command dispatch (Telegram) | `src/bot.py:_BotHandlers._dispatch()` | `dict[str, Callable]` built inline in `_dispatch` — lists every command explicitly |
| Command dispatch (Slack) | `src/platform/slack.py:SlackBot._dispatch()` | Separate `dict[str, Callable]` — partially different set from Telegram's |
| Secret collection | `src/redact.py:SecretRedactor._collect_secrets()` | Manually walks `settings.*` sub-configs, field by field |
| Service imports | `src/bot.py`, `src/platform/slack.py` | `from src import executor, repo` at module top level |
| Dep detection | `src/runtime.py:_DETECTORS` | Module-level list of `(manifest, cmd)` tuples |
| Storage init | `src/main.py:startup()` | `SQLiteStorage(DB_PATH)` hardcoded — no abstraction point |
| Audit init | `src/main.py:startup()` | `if settings.audit.audit_enabled: SQLiteAuditLog(...)` hardcoded |

> **Key gap**: There is no stable extension API. Every axis of variation (platform, AI
> backend, command, storage, service) requires editing at least one core file.

---

## Design Space

### Axis 1 — Backend & platform discovery mechanism

#### Option A — Entry-points (setuptools/importlib.metadata) *(too heavy)*

Register backends and platforms in `pyproject.toml` `[project.entry-points]`. Python's
`importlib.metadata.entry_points()` discovers them at startup.

**Pros:** True third-party plugins installable as separate packages.

**Cons:** Requires `pyproject.toml` for every plugin; adds startup overhead; overkill for
a single-container project that doesn't need PyPI distribution of individual plugins.

---

#### Option B — Decorator-based in-package registry *(recommended)*

Each subsystem module registers itself with a lightweight `Registry` object at import time.
The factory calls `registry.create(key, ...)`. No external tooling, no config file changes.

```python
# src/registry.py
from typing import Callable, TypeVar
T = TypeVar("T")

class Registry(dict):
    def register(self, key: str):
        def decorator(cls_or_fn):
            self[key] = cls_or_fn
            return cls_or_fn
        return decorator

backend_registry: Registry = Registry()
platform_registry: Registry = Registry()
command_registry: Registry = Registry()  # key -> CommandDef
```

```python
# src/ai/copilot.py
from src.registry import backend_registry

@backend_registry.register("copilot")
class CopilotBackend(AICLIBackend): ...
```

**Pros:** Zero deps; trivial to understand; a fork can delete a file and the key simply
won't be registered (clean `KeyError` at startup if selected via env var, rather than a
silent bad import).

**Cons:** Registration is order-dependent on import; must ensure all modules are imported
before `factory.create()` is called. Solved by an explicit `_load_all()` call in
`factory.py` (same pattern Python's `logging` handlers use).

**Recommendation: Option B.**

---

### Axis 2 — Shared command layer

#### Option A — Keep duplicate dispatch tables *(status quo)*

**Cons:** Commands drift. A new `gate init` in Slack was never ported to Telegram.

---

#### Option B — Unified `CommandRegistry` *(recommended)*

Define a `CommandDef` dataclass. Commands register once; both platform adapters iterate
the registry to build their dispatch tables.

```python
@dataclass
class CommandDef:
    name: str                      # e.g. "run"
    handler: str                   # attribute name on the handler object
    description: str
    platforms: set[str]            # {"telegram", "slack"} or subset
    requires_args: bool = False
    destructive: bool = False
```

```python
# src/commands/registry.py
COMMANDS: list[CommandDef] = []

def register_command(name, description, **kwargs):
    def decorator(fn):
        COMMANDS.append(CommandDef(name=name, handler=fn.__name__,
                                   description=description, **kwargs))
        return fn
    return decorator
```

Each platform adapter iterates `COMMANDS` filtered by `platforms` to build its dispatch
dict. The `gate help` command generates its text from `COMMANDS` automatically.

**Recommendation: Option B.**

---

### Axis 3 — Service injection

#### Option A — Direct module imports *(status quo)*

```python
from src import executor, repo
```

Tight coupling; monkeypatching required in tests.

---

#### Option B — `Services` dataclass injected into handlers *(recommended)*

```python
@dataclass
class Services:
    shell: ShellService          # wraps executor.run_shell
    repo: RepoService            # wraps src/repo.py functions
    runtime: RuntimeService      # wraps src/runtime.py
    redactor: SecretRedactor
    transcriber: Transcriber | None
```

Both `TelegramAdapter` and `SlackAdapter` receive a `Services` instance. Tests pass a
mock `Services`. Forks can swap `RepoService` with a `LocalRepoService` (no git clone)
by changing only `main.py`'s composition root.

**Recommendation: Option B.**

---

### Axis 4 — SecretRedactor extensibility

#### Option A — `SecretProvider` protocol *(recommended)*

Each config sub-class optionally implements `secret_values() -> list[str]`. The
`SecretRedactor` calls `secret_values()` on every sub-config it finds, rather than
hand-listing fields.

```python
class SecretProvider(Protocol):
    def secret_values(self) -> list[str]: ...
```

```python
class TelegramConfig(BaseSettings):
    bot_token: str = Field(default="", alias="TG_BOT_TOKEN")

    def secret_values(self) -> list[str]:
        return [v for v in [self.bot_token] if v]
```

```python
class SecretRedactor:
    @staticmethod
    def _collect_secrets(settings: "Settings") -> list[str]:
        # Use Pydantic v2's model_fields — the idiomatic, version-stable way to
        # enumerate declared fields without picking up Pydantic internals.
        result: list[str] = []
        for field_name in settings.model_fields:
            attr = getattr(settings, field_name)
            if isinstance(attr, SecretProvider):
                result.extend(attr.secret_values())
        return [v for v in result if v and len(v) >= 8]
```

> ⚠️ **Implementation note**: `vars(settings)` / `settings.__dict__` includes Pydantic
> internal attributes (e.g. `__pydantic_fields_set__`) that can vary across Pydantic versions.
> `settings.model_fields` (Pydantic v2 API) returns only declared field names and is the
> correct approach. The `isinstance(attr, SecretProvider)` filter is still useful as a
> second guard against non-config values.
> The test `test_collect_secrets_via_protocol` will catch any regression here.

Adding a new secret-bearing config field: add it to the sub-config's `secret_values()`
method — no change to `redact.py` required.

**Recommendation: Option A.**

---

### Axis 5 — Runtime detector extensibility

#### Option A — Plugin-registered detectors *(recommended)*

Change `_DETECTORS` from a module-level constant to a registry that can be extended:

```python
# src/runtime.py
import logging

logger = logging.getLogger(__name__)

_DETECTORS: list[tuple[str, list[str]]] = []

def register_detector(manifest: str, cmd: list[str]) -> None:
    """Register a dependency detector.

    OQ14 mitigation: all registered detectors are logged at INFO level so operators
    can audit what commands will run at startup. No allowlist enforcement — callers are
    trusted (this is internal application code, not user input).
    """
    _DETECTORS.append((manifest, cmd))
    logger.info("Dep detector registered: %s → %s", manifest, cmd)

# Built-in registrations (called at module level):
register_detector("package.json",    ["npm", "install"])
register_detector("pyproject.toml",  ["pip", "install", "-e", "."])
register_detector("requirements.txt",["pip", "install", "-r", "requirements.txt"])
register_detector("go.mod",          ["go", "mod", "download"])
```

A fork adds `register_detector("Cargo.toml", ["cargo", "build"])` in its own init
module — no `runtime.py` edit.

**Recommendation: Option A.**

---

### Axis 6 — Storage and audit backends

#### Option A — Factory + registry *(recommended)*

`ConversationStorage` and `AuditLog` are already ABCs. The only gap is that `main.py`
instantiates the concrete classes directly. Add a storage registry:

```python
storage_registry: Registry = Registry()

@storage_registry.register("sqlite")
class SQLiteStorage(ConversationStorage): ...

@storage_registry.register("memory")
class InMemoryStorage(ConversationStorage): ...
```

`main.py` calls `storage_registry.create(settings.storage.backend, DB_PATH)`. Default is
`"sqlite"`. A new `STORAGE_BACKEND=memory` env var (for testing / fork use) requires no
`main.py` edit.

**Recommendation: Option A.**

---

## Recommended Solution

- **Axis 1**: Option B — decorator-based in-package registry
- **Axis 2**: Option B — unified `CommandRegistry` with `CommandDef`
- **Axis 3**: Option B — `Services` dataclass injected into adapters
- **Axis 4**: Option A — `SecretProvider` protocol on config sub-classes
- **Axis 5**: Option A — `register_detector()` function replacing module constant
- **Axis 6**: Option A — storage/audit factory + registry

End-to-end startup flow after refactor:

```
main() → Settings.load() → _validate_config()
       → _load_registries()      # OQ16: uses a hardcoded module list (not glob/scan); see Step 5a
       → services = _build_services(settings)   # Services dataclass
       → storage  = storage_registry.create(settings.storage.storage_backend, DB_PATH)
       → audit    = audit_registry.create("null" if not settings.audit.audit_enabled
                        else settings.storage.audit_backend, AUDIT_DB_PATH)
       → backend  = backend_registry.create(settings.ai.ai_cli, settings.ai)
       → adapter  = platform_registry.create(settings.platform,
                        settings, backend, storage, services, start_time, audit)
       → await adapter.start()
```

A fork targeting only Slack + DirectAPI + no git hosting:
1. Deletes `src/platform/slack.py` — wait, that's what it keeps. Deletes `src/bot.py`,
   `src/ai/copilot.py`, `src/ai/codex.py`, `src/ai/session.py`, `src/repo.py`.
2. Sets `PLATFORM=slack`, `AI_CLI=api`.
3. Zero `ImportError` — unselected registries are simply empty; `_load_registries()` imports
   only the files that exist.
4. `RepoService` replaced by `NullRepoService` (no-op clone/pull) — set `REPO_PROVIDER=none`.

---

## Architecture Notes

- **`REPO_DIR` and `DB_PATH`** — unchanged; always import from `src/config.py`.
- **`is_stateful` flag** — unchanged on `AICLIBackend`; registry wraps the class, not
  the protocol.
- **Platform symmetry** — the unified `CommandRegistry` *enforces* symmetry: a command
  registered with `platforms={"telegram", "slack"}` must have handler methods on both
  adapters (or it raises `AttributeError` at startup).
- **Auth guards** — `@_requires_auth` for Telegram handlers and `_is_allowed()` for Slack
  handlers are preserved. The `CommandDef` can carry a `requires_auth: bool` flag so the
  adapter injects the guard automatically from the registry rather than ad-hoc per handler.
- **Lazy imports** — `_load_registries()` uses `importlib.import_module()` on each known
  path. Files that don't exist (deleted by a fork) are silently skipped. Files that fail to
  import (syntax error) raise immediately at startup with a clear message.
- **Backward compatibility** — every existing env var, command name, and default behaviour
  is preserved. This is a pure internal refactor; the user-visible API does not change.
- **Test isolation** — `Services` dataclass makes unit tests trivial: pass
  `MagicMock(spec=Services)` instead of monkeypatching global imports.
- **Modularity requirement (new)** — see "Modularity Checklist" in
  `docs/guides/feature-review-process.md`. Every new feature must declare which
  subsystem axis it touches and confirm it plugs into the registry rather than editing a
  core file directly.

---

## Config Variables

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `STORAGE_BACKEND` | `Literal["sqlite","memory"]` | `"sqlite"` | Conversation history storage backend. `memory` is for testing/forks with no `/data` volume. |
| `AUDIT_BACKEND` | `Literal["sqlite","null"]` | `"sqlite"` (when `AUDIT_ENABLED=true`) | Audit log backend. Decouples enable/disable from backend choice. |

> No existing env vars are renamed or removed.

### `StorageConfig` sub-config (new — added to `src/config.py`)

```python
class StorageConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    storage_backend: Literal["sqlite", "memory"] = Field("sqlite", alias="STORAGE_BACKEND")
    audit_backend: Literal["sqlite", "null"] = Field("sqlite", alias="AUDIT_BACKEND")

    def secret_values(self) -> list[str]:
        return []  # StorageConfig holds no secrets
```

Add to `Settings`:
```python
storage: StorageConfig = Field(default_factory=StorageConfig)
```

`main.py` then uses `settings.storage.storage_backend` and `settings.storage.audit_backend`
(as shown in Step 5c below). The `AUDIT_ENABLED` flag retains its meaning — a `False` value
still forces the `"null"` backend regardless of `AUDIT_BACKEND`.

---

## Implementation Steps

This refactor is split into five independent milestones. Each milestone leaves the test
suite green and can be merged to `develop` independently.

---

### Milestone 1 — `src/registry.py`: central registries

Create `src/registry.py`:

```python
"""Lightweight extension registries for AgentGate subsystems.

Each registry maps a string key to a factory callable.
Registrations happen at import time via the ``@registry.register(key)`` decorator.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class Registry:
    """Maps string keys to factory callables."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._map: dict[str, Callable] = {}

    def register(self, key: str, *, force: bool = False) -> Callable:
        """Decorator — register a class or factory function under *key*.

        Raises ``ValueError`` on duplicate keys unless *force=True* is passed explicitly.
        ``force=True`` is for intentional overrides in fork compositions; never use it in
        core modules.
        """
        def decorator(cls_or_fn: Callable) -> Callable:
            if key in self._map:
                if not force:
                    raise ValueError(
                        f"Registry {self._name!r}: key {key!r} already registered by "
                        f"{self._map[key]!r}. Use force=True to override intentionally."
                    )
                logger.warning(
                    "Registry %r: key %r overwritten (force=True). "
                    "Previous: %r  New: %r",
                    self._name, key, self._map[key], cls_or_fn,
                )
            self._map[key] = cls_or_fn
            return cls_or_fn
        return decorator

    def create(self, key: str, *args: Any, **kwargs: Any) -> Any:
        """Instantiate the registered factory for *key*."""
        if key not in self._map:
            available = ", ".join(sorted(self._map))
            raise ValueError(
                f"{self._name}: unknown key {key!r}. Available: {available or '(none)'}"
            )
        return self._map[key](*args, **kwargs)

    def keys(self) -> list[str]:
        return list(self._map)

    def __contains__(self, key: str) -> bool:
        return key in self._map


backend_registry:  Registry = Registry("AI backend")
platform_registry: Registry = Registry("Platform")
storage_registry:  Registry = Registry("Storage")
audit_registry:    Registry = Registry("Audit")
```

---

### Milestone 2 — `SecretProvider` protocol + config sub-class opt-in

#### Step 2a — `src/redact.py`: add `SecretProvider` protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SecretProvider(Protocol):
    """Implemented by config sub-classes that hold secret values."""
    def secret_values(self) -> list[str]: ...
```

Replace the existing `_collect_secrets` body:

```python
@staticmethod
def _collect_secrets(settings: "Settings") -> list[str]:
    result: list[str] = []
    for field_name in settings.model_fields:   # Pydantic v2 idiomatic — safer than __dict__
        attr = getattr(settings, field_name)
        if isinstance(attr, SecretProvider):
            result.extend(attr.secret_values())
    return [v for v in result if v and len(v) >= 8]
```

#### Step 2b — `src/config.py`: add `secret_values()` to each sub-config

```python
class TelegramConfig(BaseSettings):
    ...
    def secret_values(self) -> list[str]:
        return [v for v in [self.bot_token] if v]

class SlackConfig(BaseSettings):
    ...
    def secret_values(self) -> list[str]:
        return [v for v in [self.slack_bot_token, self.slack_app_token] if v]

class GitHubConfig(BaseSettings):
    ...
    def secret_values(self) -> list[str]:
        return [v for v in [self.github_repo_token] if v]

class AIConfig(BaseSettings):
    ...
    def secret_values(self) -> list[str]:
        # codex_api_key lives on the nested CodexAIConfig sub-config (self.codex),
        # not as a flat field on AIConfig. Iterate both the shared key and the nested one.
        return [v for v in [
            self.ai_api_key,
            self.codex.codex_api_key,   # nested: AIConfig.codex is a CodexAIConfig instance
        ] if v]

class VoiceConfig(BaseSettings):
    ...
    def secret_values(self) -> list[str]:
        return [v for v in [self.whisper_api_key] if v]
```

> **Effect**: adding a new secret-bearing field only requires updating `secret_values()`
> on its sub-config — `redact.py` never needs editing again.
>
> ⚠️ OQ13 — `SecretProvider` is opt-in; no static or runtime check enforces that sub-configs
> implement `secret_values()`. A new sub-config without it silently excludes its secrets
> from redaction.

---

### Milestone 3 — `Services` dataclass + service injection

#### Step 3a — Create `src/services.py`

```python
"""Service container — injected into platform adapters at startup."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.redact import SecretRedactor
    from src.transcriber import Transcriber


@dataclass
class ShellService:
    """Thin wrapper around executor.run_shell with injected configuration."""
    max_chars: int
    redactor: "SecretRedactor"

    async def run(self, cmd: str) -> str:
        from src import executor
        return await executor.run_shell(cmd, self.max_chars, self.redactor)

    def is_destructive(self, cmd: str) -> bool:
        from src import executor
        return executor.is_destructive(cmd)

    def is_exempt(self, cmd: str, keywords: list[str]) -> bool:
        from src import executor
        return executor.is_exempt(cmd, keywords)

    def sanitize_ref(self, ref: str) -> str | None:
        from src import executor
        return executor.sanitize_git_ref(ref)

    async def summarize_if_long(self, text: str, backend) -> str:
        from src import executor
        return await executor.summarize_if_long(text, self.max_chars, backend)


@dataclass
class RepoService:
    """Wraps src/repo.py. A fork can replace this with NullRepoService."""
    token: str = field(repr=False)  # OQ10 resolved — excluded from repr() via field(repr=False); not part of public interface
    repo_name: str = ""
    branch: str = "main"

    async def clone(self) -> None:
        from src import repo
        await repo.clone(self.token, self.repo_name, self.branch)

    async def pull(self) -> str:
        from src import repo
        return await repo.pull()

    async def status(self) -> str:
        from src import repo
        return await repo.status()

    async def configure_auth(self) -> None:
        from src import repo
        await repo.configure_git_auth(self.token)


class NullRepoService:
    """No-op repo service for forks that manage their own source directory.

    OQ11 resolved — does NOT inherit from RepoService (no token attribute at all).
    Implements the same duck-typed interface as RepoService (clone/pull/status/configure_auth).
    Type-checked via Protocol if strict typing is desired; no shared base class is required.
    """
    async def clone(self) -> None: pass
    async def pull(self) -> str: return "ℹ️ No repository configured."
    async def status(self) -> str: return "ℹ️ No repository configured."
    async def configure_auth(self) -> None: pass


@dataclass
class Services:
    shell: ShellService
    repo: RepoService
    redactor: "SecretRedactor"
    transcriber: "Transcriber | None" = field(default=None)
```

#### Step 3b — `src/main.py`: build `Services` and inject

```python
from src.services import Services, ShellService, RepoService

services = Services(
    shell=ShellService(
        max_chars=settings.bot.max_output_chars,
        redactor=redactor,
    ),
    repo=RepoService(
        token=settings.github.github_repo_token,
        repo_name=settings.github.github_repo,
        branch=settings.github.branch,
    ),
    redactor=redactor,
    transcriber=transcriber,
)
```

#### Step 3c — `src/bot.py` + `src/platform/slack.py`

Replace `from src import executor, repo` with `self._services: Services` received in
`__init__`. All handler methods call `self._services.shell.run(cmd)` instead of
`executor.run_shell(cmd, ...)`. All repo calls go through `self._services.repo.*`.

---

### Milestone 4 — Unified `CommandRegistry`

#### Step 4a — Create `src/commands/registry.py`

```python
"""Shared command registry — single source of truth for all bot commands."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommandDef:
    name: str                            # e.g. "run"
    handler_attr: str                    # method name on the adapter/handler object
    description: str                     # shown in `gate help`
    platforms: set[str] = field(default_factory=lambda: {"telegram", "slack"})
    requires_args: bool = False          # True = error if no args given
    destructive: bool = False            # True = gated by confirm_destructive

COMMANDS: list[CommandDef] = []


def register_command(
    name: str,
    description: str,
    *,
    platforms: set[str] | None = None,
    requires_args: bool = False,
    destructive: bool = False,
) -> "Callable":
    def decorator(fn: "Callable") -> "Callable":
        # OQ18: raise on duplicate command names, same convention as Registry.register()
        existing = {c.name for c in COMMANDS}
        if name in existing:
            raise ValueError(
                f"Command {name!r} is already registered. "
                "Apply @register_command once per command name (in bot.py only)."
            )
        COMMANDS.append(CommandDef(
            name=name,
            handler_attr=fn.__name__,
            description=description,
            platforms=platforms or {"telegram", "slack"},
            requires_args=requires_args,
            destructive=destructive,
        ))
        return fn
    return decorator
```

#### Step 4b — Rename Slack handlers and annotate in `src/bot.py`

> **Naming alignment (round 2 fix)**: The current codebase uses `cmd_*` on `_BotHandlers`
> (Telegram) and `_cmd_*` on `SlackBot` (private-prefixed). Since `CommandDef.handler_attr`
> stores the method name derived from the decorated function in `bot.py` (e.g., `"cmd_run"`),
> the Slack adapter must expose matching public method names. As part of Milestone 4,
> rename all `_cmd_*` methods in `src/platform/slack.py` to `cmd_*`. The dispatch dict is
> being removed anyway; the underscore prefix only exists to discourage external use, which
> the `Services` injection pattern already addresses.

```python
# src/bot.py  (on _BotHandlers) — @register_command applied here only (OQ3)
@register_command("run", "Execute a shell command in the repo directory",
                  platforms={"telegram", "slack"}, requires_args=True, destructive=True)
async def cmd_run(self, update, context): ...

@register_command("sync", "Pull latest changes from the remote repository",
                  platforms={"telegram", "slack"})
async def cmd_sync(self, update, context): ...
```

```python
# src/platform/slack.py — rename _cmd_* → cmd_* ; no @register_command calls (OQ3)
# SlackAdapter.cmd_run / cmd_sync / … match handler_attr from the registry.
async def cmd_run(self, event, say): ...
async def cmd_sync(self, event, say): ...
```

#### Step 4c — Generate `gate help` from `COMMANDS`

Both adapters iterate `COMMANDS` filtered by platform to produce the help string.
This replaces the hardcoded help text in both `bot.py` and `slack.py`.

#### Step 4d — Startup validation

After registrations, validate platform symmetry:

```python
def _validate_command_symmetry() -> None:
    """Raise if a command registered for both platforms is missing a handler on either."""
    both = [c for c in COMMANDS if "telegram" in c.platforms and "slack" in c.platforms]
    # Checked at startup against actual handler attributes — raises AttributeError early.
```

---

### Milestone 5 — Backend, platform, storage, audit registries

#### Step 5a — Register AI backends

In each backend file, add the decorator:

```python
# src/ai/copilot.py
from src.registry import backend_registry

@backend_registry.register("copilot")
class CopilotBackend(AICLIBackend): ...
```

Replace `factory.py`'s `if/elif` chain with:

```python
from src._loader import _module_file_exists   # shared helper — also used by main.py Step 5b

def _load_backends() -> None:
    """Import each backend module so its @backend_registry.register() decorator fires.

    OQ15 fix: distinguish "fork deleted the file" (skip silently) from "missing pip
    dependency" (re-raise with an actionable message so the operator knows to install).
    """
    import importlib
    import importlib.util

    for mod in ("src.ai.copilot", "src.ai.codex", "src.ai.direct"):
        # Convert dotted module path to a relative file path for existence check.
        rel_path = mod.replace(".", "/") + ".py"
        if importlib.util.find_spec(mod) is None and not _module_file_exists(rel_path):
            continue  # file deleted by fork — skip silently
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            # File exists but import failed → missing pip dependency or syntax error.
            raise ImportError(
                f"Failed to import backend module '{mod}'. "
                f"Is the required package installed? Original error: {exc}"
            ) from exc


def create_backend(ai: AIConfig) -> AICLIBackend:
    _load_backends()
    return backend_registry.create(ai.ai_cli, ai)
```

> `src/_loader.py` is a new thin module containing only `_module_file_exists()`. Both
> `factory.py` and `main.py` import it — keeping the logic DRY and testable in isolation.

#### Step 5b — Register platforms

```python
# src/bot.py
from src.registry import platform_registry

@platform_registry.register("telegram")
class TelegramAdapter: ...
```

```python
# src/platform/slack.py
from src.registry import platform_registry

@platform_registry.register("slack")
class SlackAdapter(SlackBot): ...  # or rename SlackBot → SlackAdapter
```

`main.py:startup()` becomes:

```python
from src.registry import platform_registry
from src._loader import _module_file_exists   # shared helper (Step 5a extraction)
import importlib
import importlib.util

def _load_platforms() -> None:
    """Import each platform module so its @platform_registry.register() decorator fires.

    OQ17 fix: uses the same find_spec + _module_file_exists() pattern as _load_backends()
    to distinguish "fork deleted the file" (skip silently) from "missing pip dependency"
    (re-raise with an actionable message). A missing slack-bolt with src/platform/slack.py
    present raises ImportError with instructions instead of a confusing ValueError later.
    """
    for mod in ("src.bot", "src.platform.slack"):
        rel_path = mod.replace(".", "/") + ".py"
        if importlib.util.find_spec(mod) is None and not _module_file_exists(rel_path):
            continue  # file deleted by fork — skip silently
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            raise ImportError(
                f"Failed to import platform module '{mod}'. "
                f"Is the required package installed? Original error: {exc}"
            ) from exc

_load_platforms()
adapter = platform_registry.create(
    settings.platform, settings, backend, storage, services, start_time, audit
)
await adapter.start()
```

> `_module_file_exists()` is defined in `src/_loader.py` (extracted in GateCode R3).
> Both `_load_backends()` (in `factory.py`) and `_load_platforms()` (in `main.py`) import it via
> `from src._loader import _module_file_exists` — see imports in the code samples above and below.

#### Step 5c — Register storage and audit backends

```python
# src/history.py
from src.registry import storage_registry

@storage_registry.register("sqlite")
class SQLiteStorage(ConversationStorage): ...

@storage_registry.register("memory")
class InMemoryStorage(ConversationStorage):
    """Volatile in-memory storage. For testing and forks without a /data volume.

    ⚠️ Not for production: history is lost on container restart.
    OQ12 resolved — enforces per-chat entry limit to prevent unbounded growth.
    """
    def __init__(self, _db_path: str = "", max_entries_per_chat: int = 200) -> None:
        self._store: dict[str, list] = {}
        self._max = max_entries_per_chat
    async def init(self) -> None: pass
    async def add_exchange(self, chat_id: str, user_msg: str, ai_msg: str) -> None:
        bucket = self._store.setdefault(chat_id, [])
        bucket.append((user_msg, ai_msg))
        if len(bucket) > self._max:
            del bucket[: len(bucket) - self._max]
    async def get_history(self, chat_id: str, limit: int = 10) -> list:
        return self._store.get(chat_id, [])[-limit:]
    async def clear(self, chat_id: str) -> None:
        self._store.pop(chat_id, None)
```

```python
# src/audit.py
from src.registry import audit_registry

@audit_registry.register("sqlite")
class SQLiteAuditLog(AuditLog): ...

@audit_registry.register("null")
class NullAuditLog(AuditLog): ...
```

`main.py` storage init:

```python
storage_backend = settings.storage.storage_backend  # "sqlite" or "memory"
storage = storage_registry.create(storage_backend, DB_PATH)
await storage.init()

# AUDIT_ENABLED=false forces null backend regardless of AUDIT_BACKEND setting
audit_backend = "null" if not settings.audit.audit_enabled else settings.storage.audit_backend
audit = audit_registry.create(audit_backend, AUDIT_DB_PATH)
await audit.init()
```

#### Step 5d — Register dep detectors (runtime.py)

Replace module-level list with `register_detector()` calls and export the function for
forks to extend:

```python
from src.runtime import register_detector
register_detector("Cargo.toml", ["cargo", "build"])
```

---

## Files to Create / Change

| File | Action | Summary of change |
|------|--------|-------------------|
| `src/registry.py` | **Create** | `Registry` class + 4 registry instances |
| `src/services.py` | **Create** | `Services`, `ShellService`, `RepoService`, `NullRepoService` dataclasses |
| `src/commands/__init__.py` | **Create** | Package marker |
| `src/commands/registry.py` | **Create** | `CommandDef`, `COMMANDS`, `@register_command` |
| `src/redact.py` | **Edit** | Add `SecretProvider` protocol; rewrite `_collect_secrets` |
| `src/config.py` | **Edit** | Add `secret_values()` to each sub-config; add `STORAGE_BACKEND` / `AUDIT_BACKEND` fields to a new `StorageConfig` sub-config |
| `src/bot.py` | **Edit** | Receive `Services`; decorate handlers with `@register_command`; register `TelegramAdapter` in `platform_registry`; remove duplicated dispatch dict |
| `src/platform/slack.py` | **Edit** | Rename `_cmd_*` → `cmd_*` handlers; receive `Services`; remove duplicated dispatch dict; register `SlackAdapter` in `platform_registry` |
| `src/platform/common.py` | **Edit** | Move `is_allowed_slack()` to `SlackAdapter` (it is not platform-agnostic) |
| `src/ai/copilot.py` | **Edit** | `@backend_registry.register("copilot")` |
| `src/ai/codex.py` | **Edit** | `@backend_registry.register("codex")` |
| `src/ai/direct.py` | **Edit** | `@backend_registry.register("api")` |
| `src/_loader.py` | **Create** | `_module_file_exists()` shared helper — imported by `factory.py` and `main.py` |
| `src/ai/factory.py` | **Edit** | Replace `if/elif` with registry lookup + `_load_backends()`; import `_module_file_exists` from `src._loader` |
| `src/history.py` | **Edit** | `@storage_registry.register("sqlite"/"memory")` |
| `src/audit.py` | **Edit** | `@audit_registry.register("sqlite"/"null")` |
| `src/runtime.py` | **Edit** | Replace `_DETECTORS` constant with `register_detector()` + export |
| `src/main.py` | **Edit** | Build `Services`; use registries for storage/audit/platform; remove `from src.platform.slack import SlackBot` import |
| `tests/unit/test_registry.py` | **Create** | Registry unit tests |
| `tests/unit/test_services.py` | **Create** | `Services` + `ShellService` + `NullRepoService` unit tests |
| `tests/unit/test_redact.py` | **Edit** | Add tests for `SecretProvider` protocol and new `_collect_secrets` |
| `tests/unit/test_config.py` | **Edit** | Add tests for `secret_values()` on each sub-config |
| `tests/unit/test_command_registry.py` | **Create** | `CommandDef` + `COMMANDS` list tests |
| `tests/integration/test_startup.py` | **Edit** | Update startup test to use registry-based init |
| `docs/roadmap.md` | **Edit** | Add item 2.16 |
| `docs/guides/feature-review-process.md` | **Edit** | Add Modularity Checklist to GateCode review criteria |
| `docs/features/remote-control-fork-project.md` | **Create** | New spec (from `_template.md`); list modular-plugin-architecture as a prerequisite in Prerequisite Questions |
| `.env.example` | **Edit** | Add commented entries for `STORAGE_BACKEND` and `AUDIT_BACKEND` |
| `docker-compose.yml.example` | **Edit** | Add commented entries for `STORAGE_BACKEND` and `AUDIT_BACKEND` |
| `.github/copilot-instructions.md` | **Edit** | Add registry, `Services`, command registry, and `SecretProvider` patterns to Architecture section |

---

## Dependencies

| Package | Status | Notes |
|---------|--------|-------|
| `importlib` (stdlib) | ✅ Built-in | Used for lazy module loading in `_load_backends()` |

No new runtime or dev dependencies.

---

## Test Plan

### `tests/unit/test_registry.py` (new)

| Test | What it checks |
|------|----------------|
| `test_register_and_create` | `registry.register("k")` → `registry.create("k", ...)` instantiates |
| `test_create_unknown_key_raises` | `registry.create("unknown")` raises `ValueError` with available keys |
| `test_register_duplicate_key_raises` | Registering same key twice raises `ValueError` (OQ9) |
| `test_register_force_overwrites` | `registry.register("k", force=True)` replaces without error and emits a `WARNING` log |
| `test_keys_returns_registered` | `.keys()` reflects all registered names |
| `test_contains` | `"k" in registry` returns `True` after registration |

### `tests/unit/test_services.py` (new)

| Test | What it checks |
|------|----------------|
| `test_null_repo_service_pull` | `NullRepoService.pull()` returns info string, no git call |
| `test_null_repo_service_clone` | `NullRepoService.clone()` is a no-op |
| `test_repo_service_token_private` | `RepoService` constructor uses `token=` kwarg; `repr()` does not contain the raw token value (OQ10) |
| `test_null_repo_service_no_token_attr` | `NullRepoService` has no `token` attribute at all — does not inherit from `RepoService` (OQ11) |
| `test_shell_service_delegates_to_executor` | `ShellService.run()` calls `executor.run_shell` |
| `test_shell_service_sanitize_ref` | Invalid ref → `None`; valid ref → shell-quoted |

### `tests/unit/test_command_registry.py` (new)

| Test | What it checks |
|------|----------------|
| `test_register_command_adds_to_commands_list` | Decorator appends `CommandDef` |
| `test_platform_filter` | Telegram-only command not returned for Slack |
| `test_help_text_generated_from_registry` | Help string contains all registered command names |
| `test_destructive_flag` | `CommandDef.destructive=True` is preserved |
| `test_validate_command_symmetry_passes` | `_validate_command_symmetry()` does not raise when both adapters expose all shared-platform handler methods |
| `test_validate_command_symmetry_raises_on_missing_handler` | `_validate_command_symmetry()` raises `AttributeError` (or equivalent) when a shared-platform command has no matching `handler_attr` on one adapter |
| `test_register_command_duplicate_name_raises` | Calling `@register_command("run", ...)` a second time raises `ValueError` (OQ18) |

### `tests/unit/test_redact.py` additions

| Test | What it checks |
|------|----------------|
| `test_secret_provider_protocol` | `TelegramConfig` satisfies `isinstance(x, SecretProvider)` |
| `test_collect_secrets_via_protocol` | `_collect_secrets` picks up values from `secret_values()` |
| `test_new_config_field_no_redact_edit` | Adding a field to `secret_values()` on sub-config is reflected without touching `redact.py` |

### `tests/unit/test_config.py` additions

| Test | What it checks |
|------|----------------|
| `test_telegram_config_secret_values` | Returns `bot_token` when set, empty list when not |
| `test_slack_config_secret_values` | Returns both tokens when set |
| `test_ai_config_secret_values` | Returns `ai_api_key` and `codex.codex_api_key` (nested field) |

### `tests/integration/test_startup.py` additions

| Test | What it checks |
|------|----------------|
| `test_platform_registry_loaded` | After `_load_registries()`, `"telegram"` and `"slack"` are in `platform_registry` |
| `test_backend_registry_loaded` | After `_load_backends()`, `"copilot"`, `"codex"`, `"api"` are in `backend_registry` |
| `test_module_file_exists_present` | `_module_file_exists("src/ai/copilot.py")` returns `True` for a real file |
| `test_module_file_exists_absent` | `_module_file_exists("src/ai/nonexistent.py")` returns `False` |
| `test_storage_registry_default` | `storage_registry.create("sqlite", ...)` returns `SQLiteStorage` |
| `test_storage_registry_memory` | `storage_registry.create("memory", ...)` returns `InMemoryStorage` |
| `test_platform_load_missing_dep_raises` | `_load_platforms()` re-raises `ImportError` with actionable message when platform file exists but required package (e.g. `slack-bolt`) is not installed (OQ17) |
| `test_platform_load_deleted_file_skipped` | `_load_platforms()` skips silently when a platform file is absent (fork use case) (OQ17) |


### `tests/contract/test_backends_contract.py` — no change

Backend contract tests already run on all registered backends; once backends are registered
via the registry they are automatically included if the contract test iterates the registry.

---

## Documentation Updates

### `docs/guides/feature-review-process.md`

Add a **Modularity Checklist** subsection under GateCode's review criteria:

```markdown
#### Modularity Checklist (GateCode)

Every feature that touches a core subsystem must verify:

- [ ] New AI backends: registered via `@backend_registry.register(key)` — `factory.py` not edited
- [ ] New platforms: registered via `@platform_registry.register(key)` — `main.py` not edited
- [ ] New storage/audit backends: registered via `@storage_registry` / `@audit_registry`
- [ ] New commands: annotated with `@register_command(...)` — dispatch tables not edited by hand
- [ ] New secret-bearing config fields: added to the sub-config's `secret_values()` — `redact.py` not edited
- [ ] New service wrappers: added to `Services` or an existing service class — not imported directly in adapters
- [ ] New dep detectors: registered via `runtime.register_detector()` — `_DETECTORS` list not edited
- [ ] Fork isolation confirmed: deleting this module's file does not cause an `ImportError` when
      the feature is not selected via env vars
```

### `README.md`

Add `STORAGE_BACKEND` and `AUDIT_BACKEND` to the environment variables table.

### `.env.example` and `docker-compose.yml.example`

Per the established lean convention (see `docs/features/align-sync`), add commented
entries only for the two new env vars:

- [ ] `.env.example` — two commented lines:
```bash
# Conversation history backend: sqlite (persistent) or memory (testing/forks). (default: sqlite)
# STORAGE_BACKEND=sqlite
# Audit log backend: sqlite or null. Effective only when AUDIT_ENABLED=true. (default: sqlite)
# AUDIT_BACKEND=sqlite
```

- [ ] `docker-compose.yml.example` — two matching commented lines under the existing env section:
```yaml
# STORAGE_BACKEND=sqlite    # history backend (sqlite | memory)
# AUDIT_BACKEND=sqlite      # audit backend (sqlite | null)
```

### `.github/copilot-instructions.md`

Add to Architecture section:

```
**Extension registries** (`src/registry.py`): `backend_registry`, `platform_registry`,
`storage_registry`, `audit_registry`. New subsystems register at import time via
`@registry.register(key)`. `factory.py` and `main.py` use the registry instead of
`if/elif` chains — do not add new branches there.

**Command registry** (`src/commands/registry.py`): all bot commands are annotated with
`@register_command(...)`. Both Telegram and Slack adapters build their dispatch tables
from `COMMANDS`. Do not add to the hardcoded dispatch dicts.

**Services dataclass** (`src/services.py`): `Services` is injected into every platform
adapter. Access shell execution via `self._services.shell.run(cmd)`, not by importing
`executor` directly. Access repo operations via `self._services.repo.*`.

**`SecretProvider` protocol** (`src/redact.py`): config sub-classes expose
`secret_values() -> list[str]`. Adding a new secret field: update `secret_values()` on
the sub-config — never edit `_collect_secrets()` in `redact.py`.
```

---

## Version Bump

No env vars renamed or removed. All changes are internal. → **MINOR** bump: `0.18.x` → `0.19.0`

---

## Roadmap Update

```markdown
| 2.16 | Modular plugin architecture — registry-based subsystems for fork cherry-picking | [→ features/modular-plugin-architecture.md](features/modular-plugin-architecture.md) |
```

---

## Edge Cases and Open Questions

1. **OQ1 — Registry import order** — `_load_backends()` imports `src.ai.copilot` etc.
   If a backend file itself imports from `src.registry` (circular?), Python's import system
   handles this as long as `registry.py` has no imports from the AI layer. Confirmed safe:
   `registry.py` has no cross-module deps.

2. **OQ2 — Fork deletes a file that is the default backend** — If a fork deletes
   `src/ai/copilot.py` but `AI_CLI` defaults to `"copilot"`, `_load_backends()` skips the
   file silently and `create_backend("copilot")` raises `ValueError` with a clear message
   listing available backends. The operator must set `AI_CLI` explicitly. This is correct
   behaviour: deleting a default is a conscious fork decision.

3. **OQ3 — `@register_command` on `_BotHandlers` vs `SlackBot`** — The decorator is
   applied to methods on different classes. The `CommandDef.handler_attr` stores only the
   method name (e.g., `"cmd_run"`); each adapter looks up `getattr(self, handler_attr)`.
   If a platform adapter doesn't have the method, `AttributeError` is raised at startup by
   the symmetry-validation step — not silently at dispatch time.

   > **Deduplication**: Each command registers once with `platforms={"telegram", "slack"}`.
   > Do NOT decorate the same command name in both `bot.py` and `slack.py` — that would
   > append two `CommandDef` entries.
   >
   > Apply `@register_command` directly on the handler method in `bot.py` (where the handler
   > is defined). `commands/registry.py` is where `CommandDef`, `COMMANDS`, and the
   > `@register_command` decorator are **defined** — not the place to call the decorator,
   > which would require importing `_BotHandlers` and create circular dependencies. The Slack
   > adapter does not call `@register_command` at all: it finds the handler via
   > `getattr(self, handler_attr)` at dispatch time.

4. **OQ4 — `InMemoryStorage` and `gate restart`** — `gate restart` recreates the AI
   backend but not the storage. `InMemoryStorage` state survives a restart. This is the
   correct behaviour for a testing backend; a fork using it in production accepts this.
   Document in the env var description.

5. **OQ5 — `Services` and `gate restart`** — `gate restart` re-creates the backend but
   the `Services` dataclass is constructed once at startup and is immutable. No issue:
   `ShellService` and `RepoService` hold config values, not the backend object.

6. **OQ6 — Slack thread scope for commands** — Unified `CommandRegistry` does not affect
   threading behaviour. Each adapter applies its own thread-aware `_reply()` / `_send()`
   after looking up the handler. No change to existing thread behaviour.

7. **OQ7 — `STORAGE_BACKEND=memory` in production** — Memory backend is volatile; a
   container restart wipes history. This is acceptable for forks that don't want persistent
   state. The env var description must call this out. No guard needed in the registry.

8. **OQ8 — Migration: existing `main.py` tests** — `tests/integration/test_startup.py`
   currently patches `SQLiteStorage` and `SQLiteAuditLog` directly. After Milestone 5 these
   are created via registry. Update test to patch `storage_registry.create` or pass
   `STORAGE_BACKEND=memory` via env — the in-memory backend eliminates the need for
   temp-file fixtures in most startup tests.

9. **OQ9 — Registry key overwrite enables backend hijacking** — ✅ *RESOLVED in R2.*
   `Registry.register()` now raises `ValueError` on duplicate keys by default.
   `force=True` parameter added for intentional fork overrides, with `logger.warning()`
   on every overwrite. See Milestone 1 code sample (lines 480–501).

10. **OQ10 — `Services.repo.token` exposes raw credential as public attribute** —
    ⚠️ *PARTIALLY RESOLVED.* `field(repr=False)` prevents accidental logging of the
    token via `repr(services.repo)`, which addresses the highest-frequency leak vector.
    However, the token remains a public attribute accessible via `self._services.repo.token`.
    This matches the existing access pattern (`self._settings.github.github_repo_token`),
    so it is *not a regression* — but the `Services` pattern encourages broader
    distribution than `_settings`. Accepted with the `repr=False` mitigation.
    Residual risk: 🟡 LOW.

11. **OQ11 — `NullRepoService` inherits `token` attribute** — ✅ *RESOLVED in R2.*
    `NullRepoService` is now a standalone class — no inheritance from `RepoService`,
    no `token` attribute at all. Implements the same duck-typed interface
    (`clone`/`pull`/`status`/`configure_auth`). See Step 3a code sample (lines 663–673).

12. **OQ12 — `InMemoryStorage` unbounded growth / no isolation** — ✅ *RESOLVED in R2.*
    `InMemoryStorage` now enforces `max_entries_per_chat=200` with eviction of oldest
    entries. Per-chat dict keys provide session isolation. See Step 5c code sample
    (lines 898–916).

13. **OQ13 — `SecretProvider` opt-in gap** — ⚠️ *MITIGATED, not fully resolved.*
    Test `test_all_sub_configs_implement_secret_provider` catches missing implementations
    in CI (see Test Plan). However, there is no *runtime* enforcement — a new sub-config
    added without `secret_values()` silently excludes its secrets from redaction until
    CI catches it. The test is sufficient for the core repo (CI is mandatory), but forks
    that skip CI inherit the gap. Residual risk: 🟡 LOW.

14. **OQ14 — `register_detector()` no command validation** — ✅ *RESOLVED in R2.*
    Accepted as internal API — callers are trusted application code, not user input.
    All registered detectors are now logged at `INFO` level for operator auditability.
    See `register_detector()` docstring (lines 306–314).

15. **OQ15 — `_load_registries()` swallows `ModuleNotFoundError`** — ✅ *RESOLVED in R2.*
    `_load_backends()` now uses `importlib.util.find_spec()` + `_module_file_exists()`
    to distinguish "fork deleted the file" (skip silently) from "missing pip
    dependency" (re-raise with actionable message). See Step 5a code sample
    (lines 819–846).

16. **OQ16 — `_load_registries()` discovery mechanism unspecified** — ✅ *RESOLVED in R2.*
    Startup flow confirmed to use a hardcoded module list (not glob/scan). Step 5a
    shows `for mod in ("src.ai.copilot", "src.ai.codex", "src.ai.direct"):` —
    explicit, auditable, not vulnerable to planted files. Comment in startup flow
    (line 368) documents this as a security invariant.


17. **OQ17 — Platform import pattern inconsistency (Step 5b)** — ✅ *RESOLVED in R2 (GateDocs).*
    Step 5b now uses a `_load_platforms()` function matching the OQ15-compliant
    `find_spec` + `_module_file_exists()` pattern from Step 5a. A missing `slack-bolt`
    with `src/platform/slack.py` present now re-raises `ImportError` with an actionable
    message instead of being silently swallowed. The `_module_file_exists()` helper is
    extracted to `src/_loader.py` (GateCode R3) so both
    `_load_backends()` and `_load_platforms()` reuse it without duplication.

18. **OQ18 — `COMMANDS` list allows duplicate command names** — ✅ *RESOLVED in R2 (GateDocs).*
    `register_command()` now checks `{c.name for c in COMMANDS}` before appending and
    raises `ValueError` if `name` is already present. Consistent with `Registry.register()`
    (which raises on duplicate keys per OQ9). Tests `test_register_command_duplicate_name_raises`
    added to `tests/unit/test_command_registry.py`.
---

## Acceptance Criteria

- [ ] All 5 milestones are implemented and merged to `develop` individually with green CI.
- [ ] `pytest tests/ -v --tb=short` passes with no failures.
- [ ] `ruff check src/` reports no new linting issues.
- [ ] A fork can delete any one of `src/bot.py`, `src/platform/slack.py`,
      `src/ai/copilot.py`, `src/ai/codex.py`, `src/ai/direct.py`, `src/repo.py`
      and the container starts without `ImportError` (provided the deleted subsystem is not
      selected via env var). *(Verified manually.)*
- [ ] All existing env vars, commands, and default behaviours are preserved.
- [ ] `Registry.register()` raises on duplicate keys by default; `force=True` is the intentional-override path (OQ9).
- [ ] `RepoService.token` is excluded from `repr()` via `field(repr=False)`; raw token value does not appear in logs or debug output (OQ10).
- [ ] `NullRepoService` does not inherit from `RepoService` — no token attribute (OQ11).
- [ ] `InMemoryStorage` enforces a per-chat entry limit (default 200) (OQ12).
- [ ] `_load_registries()` uses a hardcoded module list, not filesystem discovery (OQ16).
- [ ] All `BaseSettings` sub-classes implement `SecretProvider` (OQ13 — enforced by test).
- [ ] `_load_registries()` distinguishes "file deleted by fork" (`ImportError` + file absent) from "missing pip dep" (`ImportError` + file present); re-raises the latter with a clear message (OQ15).
- [ ] `register_detector()` logs all registered detectors at `INFO` level for auditability (OQ14).
- [ ] `docs/guides/feature-review-process.md` includes the Modularity Checklist.
- [ ] `.github/copilot-instructions.md` updated with registry and `Services` patterns.
- [ ] `README.md` updated with `STORAGE_BACKEND` and `AUDIT_BACKEND` env var rows.
- [ ] `docs/roadmap.md` item 2.16 added.
- [ ] `VERSION` bumped to `0.19.0` before merge to `main`.
- [ ] `.env.example` updated with commented entries for `STORAGE_BACKEND` and `AUDIT_BACKEND`.
- [ ] `docker-compose.yml.example` updated with matching commented entries.
- [ ] Feature works transparently on both Telegram and Slack — no behaviour change for
      existing users.
- [ ] `docs/features/remote-control-fork-project.md` created from template and lists
      this milestone as a prerequisite.
- [ ] Platform and storage/audit module loading uses the same OQ15-compliant import pattern as `_load_backends()` — not bare `try/except ImportError: pass` (OQ17).
- [ ] `register_command()` raises `ValueError` on duplicate `name` entries in `COMMANDS` (OQ18).
