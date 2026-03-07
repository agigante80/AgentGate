"""Unit tests for config.py — env var parsing, validation, defaults."""
import pytest
from pydantic import ValidationError

from src.config import AIConfig, BotConfig, GitHubConfig, SlackConfig, TelegramConfig


class TestTelegramConfig:
    def test_required_fields(self, monkeypatch):
        monkeypatch.setenv("TG_BOT_TOKEN", "tok:ABC")
        monkeypatch.setenv("TG_CHAT_ID", "12345")
        cfg = TelegramConfig()
        assert cfg.bot_token == "tok:ABC"
        assert cfg.chat_id == "12345"

    def test_fields_optional_default_empty(self):
        # TelegramConfig fields are now optional so PLATFORM=slack deployments
        # don't need to set TG_* vars.
        cfg = TelegramConfig()
        assert cfg.bot_token == ""
        assert cfg.chat_id == ""

    def test_allowed_users_default_empty(self, monkeypatch):
        monkeypatch.setenv("TG_BOT_TOKEN", "x")
        monkeypatch.setenv("TG_CHAT_ID", "1")
        cfg = TelegramConfig()
        assert cfg.allowed_users == []

    def test_allowed_users_parsed(self, monkeypatch):
        monkeypatch.setenv("TG_BOT_TOKEN", "x")
        monkeypatch.setenv("TG_CHAT_ID", "1")
        monkeypatch.setenv("ALLOWED_USERS", "[111,222,333]")
        cfg = TelegramConfig()
        assert cfg.allowed_users == [111, 222, 333]


class TestSlackConfig:
    def test_defaults(self):
        cfg = SlackConfig()
        assert cfg.slack_bot_token == ""
        assert cfg.slack_app_token == ""
        assert cfg.slack_channel_id == ""
        assert cfg.allowed_users == []

    def test_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
        cfg = SlackConfig()
        assert cfg.slack_bot_token == "xoxb-test"
        assert cfg.slack_app_token == "xapp-test"

    def test_channel_and_users_from_env(self, monkeypatch):
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C0123456")
        monkeypatch.setenv("SLACK_ALLOWED_USERS", '["U111","U222"]')
        cfg = SlackConfig()
        assert cfg.slack_channel_id == "C0123456"
        assert cfg.allowed_users == ["U111", "U222"]


class TestGitHubConfig:
    def test_defaults(self, monkeypatch):
        cfg = GitHubConfig()
        assert cfg.branch == "main"
        assert cfg.github_repo == ""
        assert cfg.github_repo_token == ""

    def test_branch_override(self, monkeypatch):
        monkeypatch.setenv("BRANCH", "develop")
        cfg = GitHubConfig()
        assert cfg.branch == "develop"


class TestBotConfig:
    def test_defaults(self):
        cfg = BotConfig()
        assert cfg.bot_cmd_prefix == "gate"
        assert cfg.max_output_chars == 3000
        assert cfg.history_enabled is True
        assert cfg.stream_responses is True

    def test_overrides(self, monkeypatch):
        monkeypatch.setenv("BOT_CMD_PREFIX", "bot")
        monkeypatch.setenv("MAX_OUTPUT_CHARS", "1500")
        monkeypatch.setenv("HISTORY_ENABLED", "false")
        monkeypatch.setenv("STREAM_RESPONSES", "false")
        cfg = BotConfig()
        assert cfg.bot_cmd_prefix == "bot"
        assert cfg.max_output_chars == 1500
        assert cfg.history_enabled is False
        assert cfg.stream_responses is False


class TestAIConfig:
    def test_default_backend(self):
        cfg = AIConfig()
        assert cfg.ai_cli == "copilot"
        assert cfg.codex_model == "o3"

    def test_codex_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        cfg = AIConfig()
        assert cfg.ai_cli == "codex"
        assert cfg.ai_api_key == "sk-test"

    def test_invalid_backend_raises(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "unknown")
        with pytest.raises(ValidationError):
            AIConfig()

    def test_ai_cli_opts_default_empty(self):
        cfg = AIConfig()
        assert cfg.ai_cli_opts == ""

    def test_ai_cli_opts_from_env(self, monkeypatch):
        monkeypatch.setenv("AI_CLI_OPTS", "--allow-all-tools --allow-url github.com")
        cfg = AIConfig()
        assert cfg.ai_cli_opts == "--allow-all-tools --allow-url github.com"
