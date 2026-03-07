from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class TelegramConfig(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    bot_token: str = Field(default="", alias="TG_BOT_TOKEN")
    chat_id: str = Field(default="", alias="TG_CHAT_ID")
    allowed_users: list[int] = Field(default=[], alias="ALLOWED_USERS")


class SlackConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    slack_bot_token: str = ""   # SLACK_BOT_TOKEN (xoxb-...)
    slack_app_token: str = ""   # SLACK_APP_TOKEN (xapp-...) for Socket Mode
    slack_channel_id: str = ""  # SLACK_CHANNEL_ID — restrict to one channel (optional)
    allowed_users: list[str] = Field(default=[], alias="SLACK_ALLOWED_USERS")  # Slack user IDs (e.g. U0123456)


class GitHubConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    github_repo_token: str = ""
    github_repo: str = ""
    branch: str = "main"


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bot_cmd_prefix: str = "gate"
    max_output_chars: int = 3000
    history_enabled: bool = True  # Set HISTORY_ENABLED=false to disable chat storage
    stream_responses: bool = True  # Set STREAM_RESPONSES=false to wait for full response
    stream_throttle_secs: float = 1.0  # Seconds between Telegram message edits during streaming
    confirm_destructive: bool = True  # Set CONFIRM_DESTRUCTIVE=false to skip confirmation prompts
    skip_confirm_keywords: list[str] = []  # e.g. SKIP_CONFIRM_KEYWORDS=push,rm — always bypassed


class AIConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ai_cli: Literal["copilot", "codex", "api"] = "copilot"

    # Copilot
    copilot_skills_dirs: str = ""

    # CLI options passthrough — passed verbatim to the backend CLI subprocess.
    # Empty (default) = each backend applies its own full-auto defaults:
    #   copilot → --allow-all  |  codex → --approval-mode full-auto
    # Non-empty = replaces the defaults entirely; must include full-auto flags if needed.
    # Ignored (with a warning) when AI_CLI=api (no subprocess).
    ai_cli_opts: str = ""

    # Generic / api backend
    ai_provider: Literal["openai", "anthropic", "ollama", "openai-compat", ""] = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""


class VoiceConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    whisper_provider: Literal["none", "openai", "local", "google"] = "none"
    whisper_api_key: str = ""  # Falls back to AIConfig.ai_api_key when provider=openai
    whisper_model: str = "whisper-1"  # For local Whisper: tiny|base|small|medium|large


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    platform: Literal["telegram", "slack"] = "telegram"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            telegram=TelegramConfig(),
            github=GitHubConfig(),
            bot=BotConfig(),
            ai=AIConfig(),
            voice=VoiceConfig(),
            slack=SlackConfig(),
        )


# Module-level path constants — import these instead of hardcoding "/repo" or "/data"
from pathlib import Path  # noqa: E402
REPO_DIR = Path("/repo")
DB_PATH = Path("/data/history.db")

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "unknown"
