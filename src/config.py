from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class TelegramConfig(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    bot_token: str = Field(default="", alias="TG_BOT_TOKEN")
    chat_id: str = Field(default="", alias="TG_CHAT_ID")
    allowed_users: list[int] = Field(default=[], alias="ALLOWED_USERS")

    def secret_values(self) -> list[str]:
        return [v for v in [self.bot_token] if v]


class SlackConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    slack_bot_token: str = ""   # SLACK_BOT_TOKEN (xoxb-...)
    slack_app_token: str = ""   # SLACK_APP_TOKEN (xapp-...) for Socket Mode
    slack_channel_id: str = ""  # SLACK_CHANNEL_ID — restrict to one channel (optional)
    allowed_users: list[str] = Field(default=[], alias="SLACK_ALLOWED_USERS")  # Slack user IDs (e.g. U0123456)
    trusted_agent_bot_ids: list[str] = Field(default=[], alias="TRUSTED_AGENT_BOT_IDS")  # Bot IDs of trusted AgentGate agents (e.g. B0123456) for agent-to-agent messaging
    slack_delete_thinking: bool = Field(True, alias="SLACK_DELETE_THINKING")  # Delete ⏳ placeholder after posting final AI response
    slack_thread_replies: bool = Field(False, alias="SLACK_THREAD_REPLIES")   # Reply in a thread anchored to the triggering message

    def secret_values(self) -> list[str]:
        return [v for v in [self.slack_bot_token, self.slack_app_token] if v]


class GitHubConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    github_repo_token: str = ""
    github_repo: str = ""
    branch: str = "main"

    def secret_values(self) -> list[str]:
        return [v for v in [self.github_repo_token] if v]


class LogConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    log_level: str = "INFO"   # LOG_LEVEL: DEBUG|INFO|WARNING|ERROR
    log_dir: str = ""         # LOG_DIR: path to write rotating log files (empty = stdout only)

    def secret_values(self) -> list[str]:
        return []


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bot_cmd_prefix: str = "gate"
    max_output_chars: int = 3000
    history_enabled: bool = True  # Set HISTORY_ENABLED=false to disable chat storage
    history_turns: int = Field(10, env="HISTORY_TURNS")  # Number of past exchanges injected per prompt; 0 = disable injection only
    stream_responses: bool = True  # Set STREAM_RESPONSES=false to wait for full response
    stream_throttle_secs: float = 1.0  # Seconds between Telegram message edits during streaming
    confirm_destructive: bool = True  # Set CONFIRM_DESTRUCTIVE=false to skip confirmation prompts
    skip_confirm_keywords: list[str] = []  # e.g. SKIP_CONFIRM_KEYWORDS=push,rm — always bypassed
    image_tag: str = ""  # IMAGE_TAG — set by docker-compose to show "latest" or "development" in ready msg
    git_sha: str = ""   # GIT_SHA — short commit hash; shown in version string for non-production builds
    prefix_only: bool = False  # PREFIX_ONLY=true: ignore messages that don't start with the bot prefix (for multi-agent Slack)
    system_prompt: str = ""  # SYSTEM_PROMPT: optional text prepended to every AI prompt (team context is auto-generated separately)
    ai_timeout_secs: int = 0                # Hard timeout for any AI backend (0 = no timeout); env: AI_TIMEOUT_SECS
    cancel_timeout_secs: int = Field(5, env="CANCEL_TIMEOUT_SECS")
    # Grace period in seconds after task.cancel() before backend.close() is called. Range: 1-60.
    thinking_slow_threshold_secs: int = 15  # Seconds of silence before first "Still thinking…" update; env: THINKING_SLOW_THRESHOLD_SECS
    thinking_update_secs: int = 30          # Seconds between subsequent elapsed-time updates; env: THINKING_UPDATE_SECS
    ai_timeout_warn_secs: int = 60          # Seconds before hard timeout to include a cancellation warning; env: AI_TIMEOUT_WARN_SECS
    thinking_show_elapsed: bool = True      # THINKING_SHOW_ELAPSED: update "🤖 Thinking…" to "🤖 Thought for Xs" after AI responds; final response posted as new message
    allow_secrets: bool = False             # ALLOW_SECRETS=true disables secret redaction in outgoing messages
    shell_allowlist: list[str] = []         # SHELL_ALLOWLIST: comma-separated permitted command names for `run` (empty = allow all)
    shell_readonly: bool = False            # SHELL_READONLY=true: only read-only commands permitted in `run`

    def secret_values(self) -> list[str]:
        return []


class CopilotAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=copilot."""

    model_config = SettingsConfigDict(extra="ignore")

    copilot_model: str = ""          # COPILOT_MODEL — overrides AI_MODEL for the Copilot CLI; empty = use AI_MODEL
    copilot_github_token: str = ""   # COPILOT_GITHUB_TOKEN — re-injected into Copilot CLI subprocess for auth
    copilot_skills_dirs: str = ""    # COPILOT_SKILLS_DIRS

    def secret_values(self) -> list[str]:
        return [v for v in [self.copilot_github_token] if v]


class CodexAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=codex."""

    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str = ""  # OPENAI_API_KEY — required when AI_CLI=codex; passed into subprocess
    codex_model: str = ""     # CODEX_MODEL — falls back to AIConfig.ai_model when empty, then "o3"

    def secret_values(self) -> list[str]:
        return [v for v in [self.openai_api_key] if v]


class DirectAIConfig(BaseSettings):
    """Fields exclusive to AI_CLI=api (DirectAPIBackend)."""

    model_config = SettingsConfigDict(extra="ignore")

    # System prompt file — path to a markdown file loaded as the system message.
    # Must not point inside REPO_DIR; mount it via a separate Docker volume.
    system_prompt_file: str = ""     # SYSTEM_PROMPT_FILE — e.g. /skills/sec-agent.md
    ai_provider: Literal["openai", "anthropic", "ollama", "openai-compat", ""] = ""
    ai_base_url: str = ""            # AI_BASE_URL — custom base URL for OpenAI-compat/Ollama
    openai_api_key: str = ""         # OPENAI_API_KEY — required when AI_PROVIDER=openai/openai-compat
    anthropic_api_key: str = ""      # ANTHROPIC_API_KEY — required when AI_PROVIDER=anthropic

    def secret_values(self) -> list[str]:
        return [v for v in [self.openai_api_key, self.anthropic_api_key] if v]


class AIConfig(BaseSettings):
    """Top-level AI configuration.

    Shared fields (ai_model, ai_cli_opts) are accessible at this level.
    Backend-exclusive fields live in the copilot / codex / direct nested configs.
    """

    model_config = SettingsConfigDict(extra="ignore")

    ai_cli: Literal["copilot", "codex", "api", "gemini"] = "copilot"

    ai_model: str = ""    # AI_MODEL — shared model name; ready_msg and codex fall back to this

    # CLI options passthrough — passed verbatim to the backend CLI subprocess.
    # Empty (default) = each backend applies its own full-auto defaults:
    #   copilot → --allow-all  |  codex → --approval-mode full-auto
    # Non-empty = replaces the defaults entirely; must include full-auto flags if needed.
    # Ignored (with a warning) when AI_CLI=api (no subprocess).
    ai_cli_opts: str = ""

    gemini_api_key: str = ""  # GEMINI_API_KEY — required when AI_CLI=gemini; no fallback

    # Backend-specific sub-configs
    copilot: CopilotAIConfig = Field(default_factory=CopilotAIConfig)
    codex: CodexAIConfig = Field(default_factory=CodexAIConfig)
    direct: DirectAIConfig = Field(default_factory=DirectAIConfig)

    def secret_values(self) -> list[str]:
        # Delegate to nested sub-configs so SecretRedactor._collect_secrets() (which only
        # iterates top-level Settings fields) still discovers all per-backend key values.
        base = self.copilot.secret_values() + self.direct.secret_values() + self.codex.secret_values()
        return base + [v for v in [self.gemini_api_key] if v]


class AuditConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    audit_enabled: bool = True  # AUDIT_ENABLED — set to false to disable audit logging

    def secret_values(self) -> list[str]:
        return []


class VoiceConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    whisper_provider: Literal["none", "openai", "local", "google"] = "none"
    whisper_api_key: str = ""  # WHISPER_API_KEY — required (no fallback) when WHISPER_PROVIDER=openai
    whisper_model: str = "whisper-1"  # For local Whisper: tiny|base|small|medium|large

    def secret_values(self) -> list[str]:
        return [v for v in [self.whisper_api_key] if v]


class StorageConfig(BaseSettings):
    """Storage and audit backend selection."""
    model_config = SettingsConfigDict(extra="ignore")

    storage_backend: Literal["sqlite", "memory"] = Field("sqlite", alias="STORAGE_BACKEND")
    audit_backend: Literal["sqlite", "null"] = Field("sqlite", alias="AUDIT_BACKEND")

    def secret_values(self) -> list[str]:
        return []


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    platform: Literal["telegram", "slack"] = "telegram"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @classmethod
    def load(cls) -> "Settings":
        import logging as _logging
        import os as _os
        import warnings as _warnings

        instance = cls(
            telegram=TelegramConfig(),
            github=GitHubConfig(),
            log=LogConfig(),
            bot=BotConfig(),
            ai=AIConfig(),
            voice=VoiceConfig(),
            slack=SlackConfig(),
            audit=AuditConfig(),
            storage=StorageConfig(),
        )

        _log = _logging.getLogger(__name__)
        if _os.environ.get("AI_API_KEY"):
            _msg = (
                "AI_API_KEY is deprecated and will be removed in v1.1.0. "
                "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or the backend-specific key instead. "
                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY as the backend-specific key."
            )
            _log.warning(_msg)
            _warnings.warn(_msg, DeprecationWarning, stacklevel=2)
        if _os.environ.get("CODEX_API_KEY"):
            _msg = (
                "CODEX_API_KEY is deprecated and will be removed in v1.1.0. "
                "Use OPENAI_API_KEY instead."
            )
            _log.warning(_msg)
            _warnings.warn(_msg, DeprecationWarning, stacklevel=2)

        return instance


# Module-level path constants — import these instead of hardcoding "/repo" or "/data"
from pathlib import Path  # noqa: E402
REPO_DIR = Path("/repo")
DB_PATH = Path("/data/history.db")
AUDIT_DB_PATH = Path("/data/audit.db")

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "unknown"
