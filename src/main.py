import asyncio
import logging
import os
import pathlib
import sys
import time

from src.config import Settings
from src.ai.factory import create_backend
from src import runtime
from src.config import REPO_DIR, DB_PATH, AUDIT_DB_PATH
from src.audit import AuditLog
from src import history  # noqa: F401 — registers @storage_registry backends
from src.logging_setup import configure_logging
from src._loader import _module_file_exists
from src.services import Services, ShellService, RepoService
from src.registry import storage_registry, audit_registry, platform_registry
logger = logging.getLogger(__name__)

_HEALTH_FILE = pathlib.Path("/tmp/healthy")
_VERSION_FILE = pathlib.Path(__file__).parent.parent / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError:
        return "unknown"


def _log_startup_banner(settings: Settings, version: str) -> None:
    sep = "=" * 56
    logger.info(sep)
    logger.info("AgentGate v%s", version)
    logger.info("  Platform : %s", settings.platform)
    logger.info("  AI       : %s", settings.ai.ai_cli)
    logger.info("  Repo     : %s", settings.github.github_repo)
    logger.info("  Branch   : %s", settings.github.branch)
    logger.info("  Log level: %s", settings.log.log_level.upper())
    logger.info("  Log dir  : %s", settings.log.log_dir or "(stdout only)")
    logger.info("  Python   : %s", sys.version.split()[0])
    logger.info("  PID      : %s", os.getpid())
    logger.info(sep)


def _validate_config(settings: Settings) -> None:
    """Raise if the required tokens for the selected platform are missing."""
    if settings.bot.history_turns < 0:
        raise ValueError("HISTORY_TURNS must be >= 0")
    if settings.platform == "telegram":
        if not settings.telegram.bot_token:
            raise ValueError("TG_BOT_TOKEN is required when PLATFORM=telegram")
        if not settings.telegram.chat_id:
            raise ValueError("TG_CHAT_ID is required when PLATFORM=telegram")
    elif settings.platform == "slack":
        if not settings.slack.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required when PLATFORM=slack")
        if not settings.slack.slack_app_token:
            raise ValueError("SLACK_APP_TOKEN is required when PLATFORM=slack")
        if not settings.slack.slack_channel_id:
            raise ValueError(
                "SLACK_CHANNEL_ID is required when PLATFORM=slack — "
                "set it to the channel where the bot should operate"
            )

    ai = settings.ai
    if ai.ai_cli == "codex" and not ai.codex.openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set when AI_CLI=codex")
    if ai.ai_cli == "gemini" and not ai.gemini_api_key:
        raise ValueError("GEMINI_API_KEY must be set when AI_CLI=gemini")
    if ai.ai_cli == "api":
        if ai.direct.ai_provider in ("openai", "openai-compat") and not ai.direct.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when AI_CLI=api and "
                f"AI_PROVIDER={ai.direct.ai_provider}"
            )
        if ai.direct.ai_provider == "anthropic" and not ai.direct.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY must be set when AI_CLI=api and AI_PROVIDER=anthropic"
            )

    voice = settings.voice
    if voice.whisper_provider == "openai" and not voice.whisper_api_key:
        raise ValueError("WHISPER_API_KEY must be set when WHISPER_PROVIDER=openai")


def _load_platforms() -> None:
    """Import platform modules so their @platform_registry.register() decorators fire."""
    import importlib
    import importlib.util

    for mod in ("src.bot", "src.platform.slack"):
        rel_path = mod.replace(".", "/") + ".py"
        if importlib.util.find_spec(mod) is None and not _module_file_exists(rel_path):
            continue
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            raise ImportError(
                f"Failed to import platform module '{mod}'. "
                f"Is the required package installed? Original error: {exc}"
            ) from exc


async def _install_commit_msg_hook() -> None:
    """Install a commit-msg hook that warns if secrets are committed.

    The hook is installed unconditionally — git history is permanent and
    ALLOW_SECRETS only controls output redaction, not commit-time scanning.
    """
    hooks_dir = REPO_DIR / ".git" / "hooks"
    hook_file = hooks_dir / "commit-msg"
    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_script = (
            "#!/usr/bin/env python3\n"
            "\"\"\"Reject commits whose message or staged diff contain common secret patterns.\"\"\"\n"
            "import re, subprocess, sys\n"
            "_PATTERNS = [\n"
            "    re.compile(r'ghp_[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'gho_[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'ghs_[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'ghr_[A-Za-z0-9]{36,}'),\n"
            "    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),\n"
            "    re.compile(r'xoxb-[A-Za-z0-9\\-]{20,}'),\n"
            "    re.compile(r'xoxp-[A-Za-z0-9\\-]{20,}'),\n"
            "    re.compile(r'xapp-[A-Za-z0-9\\-]{20,}'),\n"
            "    re.compile(r'xoxs-[A-Za-z0-9\\-]{20,}'),\n"
            "    re.compile(r'sk-(?:proj-|org-|svcacct-|ant-api03-)?[A-Za-z0-9\\-_]{20,}'),\n"
            "    re.compile(r'Bearer\\s+[A-Za-z0-9\\-._~+/]{20,}=*'),\n"
            "    re.compile(r'https?://[^\\s@]+:[^\\s@]+@[^\\s]+'),\n"
            "]\n"
            "_SKIP_PATHS = ('tests/', 'test_', '.md', '.txt')\n"
            "def check(text):\n"
            "    for p in _PATTERNS:\n"
            "        if p.search(text): return True\n"
            "    return False\n"
            "def filter_diff(diff):\n"
            "    \"\"\"Return diff lines excluding test files and comment-like additions.\"\"\"\n"
            "    lines = []; in_skip = False\n"
            "    for line in diff.splitlines():\n"
            "        if line.startswith('diff --git'):\n"
            "            in_skip = any(s in line for s in _SKIP_PATHS)\n"
            "        if not in_skip and line.startswith('+') and not line.startswith('+++'):\n"
            "            lines.append(line)\n"
            "    return '\\n'.join(lines)\n"
            "msg = open(sys.argv[1]).read()\n"
            "raw_diff = subprocess.run(['git', 'diff', '--cached'], capture_output=True, text=True).stdout\n"
            "diff = filter_diff(raw_diff)\n"
            "if check(msg) or check(diff):\n"
            "    print('\\033[31m[commit-msg hook] BLOCKED: possible secret detected in commit message or staged diff.')\n"
            "    print('Remove the secret before committing — git history is permanent.\\033[0m')\n"
            "    sys.exit(1)\n"
        )
        hook_file.write_text(hook_script)
        hook_file.chmod(0o755)
        logger.info("Commit-msg hook installed at %s", hook_file)
    except Exception:
        logger.warning("Could not install commit-msg hook at %s", hook_file, exc_info=True)


async def startup(settings: Settings) -> None:
    start_time = time.time()

    from src import repo
    token = settings.github.github_repo_token
    logger.info("Cloning repository…")
    await repo.clone(
        token,
        settings.github.github_repo,
        settings.github.branch,
    )
    await repo.configure_git_auth(token)
    await _install_commit_msg_hook()

    logger.info("Installing dependencies…")
    dep_result = await runtime.install_deps()
    logger.info(dep_result)

    logger.info("Initializing conversation history DB…")
    storage_backend = getattr(settings.storage, "storage_backend", "sqlite")
    storage = storage_registry.create(storage_backend, DB_PATH)
    await storage.init()

    logger.info("Initializing audit log…")
    audit: AuditLog
    audit_enabled = getattr(settings.audit, "audit_enabled", True)
    audit_backend = "null" if not audit_enabled else getattr(settings.storage, "audit_backend", "sqlite")
    audit = audit_registry.create(audit_backend, AUDIT_DB_PATH)
    await audit.init()
    if not await audit.verify():
        logger.error(
            "Audit log verification FAILED — audit records may not be "
            "persisting.  Check file permissions and disk space at %s",
            AUDIT_DB_PATH,
        )
    if audit_enabled:
        logger.info("Audit log enabled at %s", AUDIT_DB_PATH)
    else:
        logger.info("Audit log disabled (AUDIT_ENABLED=false)")

    logger.info("Initializing AI backend: %s", settings.ai.ai_cli)
    backend = create_backend(settings.ai)

    from src.redact import SecretRedactor
    redactor = SecretRedactor(settings)
    services = Services(
        shell=ShellService(
            max_chars=settings.bot.max_output_chars,
            redactor=redactor,
            allowlist=settings.bot.shell_allowlist,
            readonly=settings.bot.shell_readonly,
        ),
        repo=RepoService(
            token=settings.github.github_repo_token,
            repo_name=settings.github.github_repo,
            branch=settings.github.branch,
        ),
        redactor=redactor,
        transcriber=None,
    )

    logger.info("Starting platform: %s", settings.platform)
    _load_platforms()
    adapter = platform_registry.create(
        settings.platform,
        settings, backend, storage, services, start_time, audit,
    )
    await adapter.start()


def main() -> None:
    version = _read_version()
    try:
        settings = Settings.load()
        _validate_config(settings)
    except Exception as exc:
        # Basic fallback logging before configure_logging has run
        logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    configure_logging(settings.log.log_level, settings.log.log_dir)
    _log_startup_banner(settings, version)

    try:
        asyncio.run(startup(settings))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down.")


if __name__ == "__main__":  # pragma: no cover
    main()
