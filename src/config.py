from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class TelegramConfig(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    bot_token: str = Field(alias="TG_BOT_TOKEN")
    chat_id: str = Field(alias="TG_CHAT_ID")
    allowed_users: list[int] = Field(default=[], alias="ALLOWED_USERS")


class GitHubConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    github_token: str = ""
    github_repo: str = ""
    branch: str = "main"


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bot_cmd_prefix: str = "ta"
    max_output_chars: int = 3000
    history_enabled: bool = True  # Set HISTORY_ENABLED=false to disable chat storage
    stream_responses: bool = True  # Set STREAM_RESPONSES=false to wait for full response
    stream_throttle_secs: float = 1.0  # Seconds between Telegram message edits during streaming


class AIConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ai_cli: Literal["copilot", "codex", "api"] = "copilot"

    # Copilot
    copilot_model: str = ""
    copilot_skills_dirs: str = ""

    # Codex
    codex_model: str = "o3"

    # Generic / api backend
    ai_provider: Literal["openai", "anthropic", "ollama", "openai-compat", ""] = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    ai: AIConfig = Field(default_factory=AIConfig)

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            telegram=TelegramConfig(),
            github=GitHubConfig(),
            bot=BotConfig(),
            ai=AIConfig(),
        )


# Module-level path constants — import these instead of hardcoding "/repo" or "/data"
from pathlib import Path  # noqa: E402
REPO_DIR = Path("/repo")
DB_PATH = Path("/data/history.db")

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "unknown"
