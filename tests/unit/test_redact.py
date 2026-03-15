"""Unit tests for src/redact.py — SecretRedactor."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.config import Settings, BotConfig, TelegramConfig, SlackConfig, GitHubConfig, AIConfig, VoiceConfig
from src.redact import SecretRedactor


def _make_settings(
    allow_secrets: bool = False,
    bot_token: str = "",
    slack_bot_token: str = "",
    slack_app_token: str = "",
    github_token: str = "",
    ai_api_key: str = "",
    whisper_api_key: str = "",
) -> Settings:
    bot = MagicMock(spec=BotConfig)
    bot.allow_secrets = allow_secrets
    tg = MagicMock(spec=TelegramConfig)
    tg.bot_token = bot_token
    slack = MagicMock(spec=SlackConfig)
    slack.slack_bot_token = slack_bot_token
    slack.slack_app_token = slack_app_token
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo_token = github_token
    ai = MagicMock(spec=AIConfig)
    ai.ai_api_key = ai_api_key
    voice = MagicMock(spec=VoiceConfig)
    voice.whisper_api_key = whisper_api_key
    settings = MagicMock(spec=Settings)
    settings.bot = bot
    settings.telegram = tg
    settings.slack = slack
    settings.github = gh
    settings.ai = ai
    settings.voice = voice
    return settings


class TestRedactDisabled:
    def test_allow_secrets_true_returns_text_unchanged(self):
        settings = _make_settings(allow_secrets=True, slack_bot_token="xoxb-abc123def456ghi789jkl0")
        redactor = SecretRedactor(settings)
        text = "token is xoxb-abc123def456ghi789jkl0 ok"
        assert redactor.redact(text) == text

    def test_empty_text_returns_unchanged(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        assert redactor.redact("") == ""

    def test_none_like_empty_no_crash(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        assert redactor.redact("") == ""


class TestPatternRedaction:
    def test_github_pat_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "token ghp_" + "A" * 36 + " used here"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "ghp_" not in result

    def test_slack_bot_token_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "SLACK_BOT_TOKEN=xoxb-" + "X" * 30
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "xoxb-" not in result

    def test_openai_key_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "key=sk-" + "a" * 25 + " rest"
        result = redactor.redact(text)
        assert "[REDACTED]" in result

    def test_openai_proj_key_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "key=sk-proj-abc123def456ghi789jkl0mnopqr rest"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "sk-proj-" not in result

    def test_openai_org_key_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "key=sk-org-xyz987uvw654rst321qpo098 rest"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "sk-org-" not in result

    def test_openai_svcacct_key_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "AI_API_KEY=sk-svcacct-abc123def456ghi789jkl0mnopqr"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "sk-svcacct-" not in result

    def test_anthropic_key_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "ANTHROPIC_KEY=sk-ant-api03-abc123def456ghi789jkl0mn rest"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "sk-ant-api03-" not in result

    def test_url_with_creds_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "origin https://user:password@github.com/repo.git"
        result = redactor.redact(text)
        assert "[REDACTED]" in result
        assert "password" not in result

    def test_safe_text_unchanged(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        text = "No secrets here. Just normal text."
        assert redactor.redact(text) == text

    def test_short_sk_strings_not_redacted(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        short_strings = [
            "sk-test",
            "sk-proj-short",
            "sk-org-abc",
            "sk-ant-api03-brief",
            "config key sk-mode is fine",
        ]
        for text in short_strings:
            assert redactor.redact(text) == text, f"Short sk- string was incorrectly redacted: {text!r}"


class TestKnownValueRedaction:
    def test_known_value_redacted(self):
        token = "xoxb-known-token-value-for-testing-1234567"
        settings = _make_settings(slack_bot_token=token)
        redactor = SecretRedactor(settings)
        text = f"The token is {token} and it should be hidden."
        result = redactor.redact(text)
        assert token not in result
        assert "[REDACTED]" in result

    def test_short_value_not_collected(self):
        settings = _make_settings(slack_bot_token="short")
        redactor = SecretRedactor(settings)
        # "short" is only 5 chars — not in known values — won't be redacted as value
        # (it might still match a pattern, but "short" doesn't match any pattern)
        text = "this is short text"
        assert redactor.redact(text) == text


class TestRedactGitCommitCmd:
    def test_non_commit_cmd_unchanged(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        cmd = "git status"
        assert redactor.redact_git_commit_cmd(cmd) == cmd

    def test_git_commit_redacts_secrets(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        secret = "ghp_" + "A" * 36
        cmd = f'git commit -m "update token {secret}"'
        result = redactor.redact_git_commit_cmd(cmd)
        assert secret not in result
        assert "[REDACTED]" in result

    def test_git_C_commit_redacts(self):
        settings = _make_settings()
        redactor = SecretRedactor(settings)
        secret = "xoxb-" + "B" * 30
        cmd = f'git -C /repo commit -m "set slack token {secret}"'
        result = redactor.redact_git_commit_cmd(cmd)
        assert secret not in result

    def test_disabled_commit_redact_returns_cmd(self):
        settings = _make_settings(allow_secrets=True)
        redactor = SecretRedactor(settings)
        secret = "ghp_" + "A" * 36
        cmd = f'git commit -m "token {secret}"'
        assert redactor.redact_git_commit_cmd(cmd) == cmd


class TestSecretProvider:
    def test_telegram_config_satisfies_protocol(self):
        from src.redact import SecretProvider
        from src.config import TelegramConfig
        cfg = TelegramConfig()
        assert isinstance(cfg, SecretProvider)

    def test_collect_secrets_via_protocol(self):
        """_collect_secrets picks up values via secret_values() on each sub-config."""
        from src.config import Settings, TelegramConfig, BotConfig
        s = Settings()
        # Inject a real telegram config with a token
        s.telegram = TelegramConfig(TG_BOT_TOKEN="ghp_" + "A" * 36)
        secrets = SecretRedactor._collect_secrets(s)
        assert "ghp_" + "A" * 36 in secrets

    def test_new_config_field_no_redact_edit(self, monkeypatch):
        """Adding a field to secret_values() on sub-config works without touching redact.py."""
        from src.config import GitHubConfig, Settings
        long_token = "ghp_" + "B" * 36
        monkeypatch.setenv("GITHUB_REPO_TOKEN", long_token)
        s = Settings()
        secrets = SecretRedactor._collect_secrets(s)
        assert long_token in secrets
