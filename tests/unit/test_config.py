"""Unit tests for config.py — env var parsing, validation, defaults."""
import pytest
from pydantic import ValidationError

from src.config import AIConfig, BotConfig, GitHubConfig, TelegramConfig


class TestTelegramConfig:
    def test_required_fields(self, monkeypatch):
        monkeypatch.setenv("TG_BOT_TOKEN", "tok:ABC")
        monkeypatch.setenv("TG_CHAT_ID", "12345")
        cfg = TelegramConfig()
        assert cfg.bot_token == "tok:ABC"
        assert cfg.chat_id == "12345"

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


class TestGitHubConfig:
    def test_defaults(self, monkeypatch):
        cfg = GitHubConfig()
        assert cfg.branch == "main"
        assert cfg.github_repo == ""
        assert cfg.github_token == ""

    def test_branch_override(self, monkeypatch):
        monkeypatch.setenv("BRANCH", "develop")
        cfg = GitHubConfig()
        assert cfg.branch == "develop"


class TestBotConfig:
    def test_defaults(self):
        cfg = BotConfig()
        assert cfg.bot_cmd_prefix == "ta"
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
