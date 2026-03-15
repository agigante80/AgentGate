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
| GateCode | 1     | -/10  | -          | Pending |
| GateSec  | 1     | 6/10  | 2026-03-15 (9130578) | 8 OQs added (OQ9–OQ16): registry hijack, token exposure, InMemoryStorage bounds, SecretProvider gap, ImportError swallowing, detector injection, discovery mechanism. See inline `⚠️` annotations. |
| GateDocs | 1     | 6/10  | 2026-03-15 | 5 blockers fixed (OQ9 code/test mismatch, OQ10/11 code/criteria mismatch, `vars(settings)` Pydantic incompatibility, `AIConfig.codex` wrong reference, InMemoryStorage code/test desync). 6 gaps addressed (`.env.example` added, OQ14 test, OQ15 AC, COMMANDS dedup note, OQ16 comment corrected, `remote-control-fork-project.md` added to Files table). |

**Status**: ⏳ In review
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
        # Iterate known sub-config attributes directly — Pydantic BaseSettings does not
        # expose nested model instances via vars() / __dict__ in a consistent way.
        result: list[str] = []
        for attr in vars(settings).values():
            if isinstance(attr, SecretProvider):
                result.extend(attr.secret_values())
        return [v for v in result if v and len(v) >= 8]
```

> ⚠️ **Implementation note**: `vars(settings)` does not enumerate Pydantic sub-model
> attributes in all Pydantic versions. The safe implementation iterates
> `settings.__dict__.values()` after `Settings.load()` has been called (which
> populates all sub-configs as instance attributes). In practice this works because
> `Settings.__init__` assigns `self.telegram`, `self.slack`, etc. as plain attributes.
> If a future Pydantic upgrade changes this, the correct fallback is:
> ```python
> for field_name in settings.model_fields:
>     attr = getattr(settings, field_name)
>     if isinstance(attr, SecretProvider):
>         result.extend(attr.secret_values())
> ```
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
_DETECTORS: list[tuple[str, list[str]]] = []

def register_detector(manifest: str, cmd: list[str]):
    # ⚠️ OQ14 — no validation on cmd; arbitrary command injection if called by untrusted code
    _DETECTORS.append((manifest, cmd))

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
       → storage  = storage_registry.create(settings.storage.backend)
       → audit    = audit_registry.create(...)
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
            if key in self._map and not force:
                raise ValueError(
                    f"Registry {self._name!r}: key {key!r} already registered by "
                    f"{self._map[key]!r}. Use force=True to override intentionally."
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
    for attr in settings.__dict__.values():   # see implementation note in Design Space
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
        # codex_api_key is a flat field on AIConfig, not a nested sub-config.
        # See src/config.py — CodexConfig is not a separate sub-config instance.
        return [v for v in [
            self.ai_api_key,
            self.codex_api_key,   # flat field, aliased CODEX_API_KEY
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
    _token: str       # OQ10 resolved — stored as private field; not in repr(), not in public interface
    repo_name: str
    branch: str

    async def clone(self) -> None:
        from src import repo
        await repo.clone(self._token, self.repo_name, self.branch)

    async def pull(self) -> str:
        from src import repo
        return await repo.pull()

    async def status(self) -> str:
        from src import repo
        return await repo.status()

    async def configure_auth(self) -> None:
        from src import repo
        await repo.configure_git_auth(self._token)


class NullRepoService:
    """No-op repo service for forks that manage their own source directory.

    OQ11 resolved — does NOT inherit from RepoService (no token attribute at all).
    Implements the same interface via duck typing / ABC (see RepoServiceABC below).
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

#### Step 4b — Annotate existing handler methods in `src/bot.py` and `src/platform/slack.py`

```python
# src/bot.py  (on _BotHandlers)
@register_command("run", "Execute a shell command in the repo directory",
                  platforms={"telegram", "slack"}, requires_args=True, destructive=True)
async def cmd_run(self, update, context): ...

@register_command("sync", "Pull latest changes from the remote repository",
                  platforms={"telegram", "slack"})
async def cmd_sync(self, update, context): ...
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
def _load_backends() -> None:
    import importlib
    for mod in ("src.ai.copilot", "src.ai.codex", "src.ai.direct"):
        try:
            importlib.import_module(mod)
        except ImportError:
            pass  # ⚠️ OQ15 — also swallows ModuleNotFoundError from missing pip deps

def create_backend(ai: AIConfig) -> AICLIBackend:
    _load_backends()
    return backend_registry.create(ai.ai_cli, ai)
```

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
import importlib

for mod in ("src.bot", "src.platform.slack"):
    try: importlib.import_module(mod)
    except ImportError: pass

adapter = platform_registry.create(
    settings.platform, settings, backend, storage, services, start_time, audit
)
await adapter.start()
```

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
backend_name = settings.storage.backend  # new field, default "sqlite"
storage = storage_registry.create(backend_name, DB_PATH)
await storage.init()

audit_backend = "sqlite" if settings.audit.audit_enabled else "null"
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
| `src/platform/slack.py` | **Edit** | Receive `Services`; decorate handlers with `@register_command`; register `SlackAdapter`; remove duplicated dispatch dict |
| `src/platform/common.py` | **Edit** | Move `is_allowed_slack()` to `SlackAdapter` (it is not platform-agnostic) |
| `src/ai/copilot.py` | **Edit** | `@backend_registry.register("copilot")` |
| `src/ai/codex.py` | **Edit** | `@backend_registry.register("codex")` |
| `src/ai/direct.py` | **Edit** | `@backend_registry.register("api")` |
| `src/ai/factory.py` | **Edit** | Replace `if/elif` with registry lookup + `_load_backends()` |
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
| `test_register_force_overwrites` | `registry.register("k", force=True)` replaces without error |
| `test_keys_returns_registered` | `.keys()` reflects all registered names |
| `test_contains` | `"k" in registry` returns `True` after registration |

### `tests/unit/test_services.py` (new)

| Test | What it checks |
|------|----------------|
| `test_null_repo_service_pull` | `NullRepoService.pull()` returns info string, no git call |
| `test_null_repo_service_clone` | `NullRepoService.clone()` is a no-op |
| `test_repo_service_token_private` | `RepoService` has no public `.token` attribute; `repr()` does not contain raw token (OQ10) |
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
| `test_ai_config_secret_values` | Returns `ai_api_key` and `codex_api_key` |

### `tests/integration/test_startup.py` additions

| Test | What it checks |
|------|----------------|
| `test_platform_registry_loaded` | After `_load_registries()`, `"telegram"` and `"slack"` are in `platform_registry` |
| `test_backend_registry_loaded` | After `_load_backends()`, `"copilot"`, `"codex"`, `"api"` are in `backend_registry` |
| `test_storage_registry_default` | `storage_registry.create("sqlite", ...)` returns `SQLiteStorage` |
| `test_storage_registry_memory` | `storage_registry.create("memory", ...)` returns `InMemoryStorage` |


### `tests/unit/test_registry.py` security additions (GateSec)

| Test | What it checks |
|------|----------------|
| `test_register_duplicate_key_raises` | Registering same key twice raises `ValueError` (OQ9 fix) |
| `test_register_force_overwrites_silently` | `register(..., force=True)` replaces without error — intentional fork override path |

### `tests/unit/test_services.py` security additions (GateSec)

| Test | What it checks |
|------|----------------|
| `test_null_repo_service_has_no_token_attr` | `NullRepoService` has no `.token` attribute — does not inherit `RepoService` (OQ11) |
| `test_repo_service_token_not_public` | `RepoService` has no public `.token` attribute; `repr()` does not expose the credential (OQ10) |

### `tests/unit/test_runtime.py` additions (OQ14)

| Test | What it checks |
|------|----------------|
| `test_register_detector_appears_in_detectors` | `register_detector("Cargo.toml", ["cargo","build"])` adds the pair to `_DETECTORS` |
| `test_register_detector_logged_at_startup` | All registered detectors are logged at `INFO` level during startup for auditability (OQ14 mitigation) |

### `tests/unit/test_redact.py` security additions (GateSec)

| Test | What it checks |
|------|----------------|
| `test_all_sub_configs_implement_secret_provider` | Every `BaseSettings` sub-class in `config.py` satisfies `SecretProvider` protocol (OQ13) |
| `test_collect_secrets_uses_dict_not_vars` | `_collect_secrets` correctly enumerates sub-configs via `settings.__dict__` (Pydantic compatibility) |

### `tests/unit/test_storage_memory.py` security additions (GateSec)

| Test | What it checks |
|------|----------------|
| `test_memory_storage_respects_max_entries` | After `max_entries_per_chat` exchanges, oldest are evicted |
| `test_memory_storage_chat_isolation` | `get_history("chat_a")` never returns data from `"chat_b"` |
| `test_memory_storage_default_max_is_finite` | Default `max_entries_per_chat` is 200 (not unbounded) |
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
   > append two `CommandDef` entries. Apply `@register_command` in `bot.py` only (or a
   > shared `commands/definitions.py`). The Slack adapter looks up the handler by
   > `handler_attr` name on itself; it does not need to register the command again.

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

9. **OQ9 — Registry key overwrite enables backend hijacking** — `Registry.register()`
   logs a warning but *allows* overwriting an existing key. If `_load_registries()` imports
   modules in sequence and a later import re-registers an existing key (e.g., a fork's
   `custom_copilot.py` registers `"copilot"` over the real one), the legitimate backend is
   silently replaced. Combined with `pip install -e .` on the user's repo (runtime.py line 12),
   which can inject packages into `sys.path`, this creates a backend-hijacking vector.
   **Recommendation**: raise `ValueError` on duplicate keys by default; add an explicit
   `force=True` parameter for intentional overrides. Severity: 🔴 HIGH.

10. **OQ10 — `Services.repo.token` exposes raw credential as public attribute** —
    `RepoService` stores `github_repo_token` as a plain public `str` attribute. Since
    `Services` is injected into every platform adapter, every handler method can read
    `self._services.repo.token` directly. While `self._settings.github.github_repo_token`
    is equally accessible today, the `Services` dataclass is explicitly designed to be
    passed around freely and is the *recommended* interface post-refactor. Consider using
    a private attribute with a getter, or passing the token only at `clone()`/`configure_auth()`
    call sites. Severity: 🟡 MEDIUM.

11. **OQ11 — `NullRepoService` inherits `token` attribute** — `NullRepoService` subclasses
    `RepoService` and defaults `token=""`, but the attribute is still public. A fork
    misconfiguration (e.g., `REPO_PROVIDER=none` while `REPO_TOKEN` is set) would store
    the token in `NullRepoService` where it's never used for cloning but is accessible to
    every handler via `services.repo.token`. **Recommendation**: override `__init__` to
    discard the token, or don't inherit from `RepoService` — use the same ABC instead.
    Severity: 🟡 MEDIUM.

12. **OQ12 — `InMemoryStorage` unbounded growth / no isolation** — The proposed
    `InMemoryStorage` uses `dict[str, list]` with no TTL, no maximum size, and no
    per-chat memory cap. In a multi-user production fork, memory grows without bound.
    Additionally, `InMemoryStorage` survives `gate restart` (OQ4 acknowledges this) while
    the backend is re-created, leading to history/state inconsistency.
    **Recommendation**: add `max_entries_per_chat: int = 1000` constructor parameter;
    document `STORAGE_BACKEND=memory` as test-only in the env var description.
    Severity: 🟡 MEDIUM.

13. **OQ13 — `SecretProvider` opt-in gap** — The `SecretProvider` protocol is
    `@runtime_checkable` and `_collect_secrets` uses `isinstance()`. If a new sub-config
    class holds secrets but forgets to implement `secret_values()`, its secrets are
    silently excluded from redaction — the same class of bug that caused the v0.13.0
    `CODEX_API_KEY` leak. The problem is moved, not solved.
    **Recommendation**: add a startup assertion in `_collect_secrets` that all sub-config
    classes satisfy `isinstance(attr, SecretProvider)`, or add a unit test that enumerates
    sub-configs and asserts the protocol. Severity: 🟡 MEDIUM.

14. **OQ14 — `register_detector()` no command validation** — The function accepts arbitrary
    `cmd: list[str]`. While `_DETECTORS` is currently a module-level constant (pre-existing
    risk), making it extensible at runtime via `register_detector()` widens the attack
    surface: any imported code can register arbitrary commands that execute at startup via
    `asyncio.create_subprocess_exec`. **Recommendation**: validate commands against an
    allowlist of known package managers, or log all registered detectors at startup for
    auditability. Severity: 🟡 MEDIUM.

15. **OQ15 — `_load_registries()` swallows `ModuleNotFoundError`** — `except ImportError: pass`
    is intended to handle "fork deleted this backend file" but `ModuleNotFoundError` (a
    subclass of `ImportError`) is also caught. If a backend has a missing pip dependency
    (e.g., `import anthropic` fails in `direct.py`), the backend is silently skipped rather
    than raising a clear installation error. The operator gets a confusing `ValueError:
    unknown key 'api'` at `registry.create()` time.
    **Recommendation**: catch `ImportError`, check if the module file exists on disk, and
    re-raise if it does (indicating a dependency issue, not a deleted file). Or use
    `importlib.util.find_spec()` first to distinguish "file missing" from "import failed".
    Severity: 🟡 MEDIUM.

16. **OQ16 — `_load_registries()` discovery mechanism unspecified** — The startup flow
    comment says "imports all src/ai/\*, src/platform/\*, src/storage/\*" but the code sample
    shows a hardcoded list of module paths. If the implementation uses filesystem glob/scan
    instead of a hardcoded list, a file planted in `src/ai/` by a malicious repo checkout
    (in dev environments where `REPO_DIR` overlaps with the application directory) could be
    auto-discovered and imported. **Recommendation**: always use a hardcoded module list in
    `_load_registries()`, never `os.listdir()` or `pkgutil.iter_modules()`. Document this
    as a security invariant. Severity: 🟡 MEDIUM.

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
- [ ] `RepoService._token` is private; no public `.token` attribute; `repr()` does not expose credential (OQ10).
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
