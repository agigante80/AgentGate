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
        assert cfg.ai_timeout_secs == 0       # 2.15: no-timeout default
        assert cfg.history_turns == 10        # 2.10: default injection window

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

    def test_history_turns_env(self, monkeypatch):
        monkeypatch.setenv("HISTORY_TURNS", "5")
        cfg = BotConfig()
        assert cfg.history_turns == 5

    def test_history_turns_zero(self, monkeypatch):
        monkeypatch.setenv("HISTORY_TURNS", "0")
        cfg = BotConfig()
        assert cfg.history_turns == 0

    def test_ai_timeout_env(self, monkeypatch):
        monkeypatch.setenv("AI_TIMEOUT_SECS", "720")
        cfg = BotConfig()
        assert cfg.ai_timeout_secs == 720

    def test_thinking_show_elapsed_default(self):
        """THINKING_SHOW_ELAPSED defaults to True."""
        cfg = BotConfig()
        assert cfg.thinking_show_elapsed is True

    def test_thinking_show_elapsed_disabled(self, monkeypatch):
        """THINKING_SHOW_ELAPSED=false disables elapsed-time edit."""
        monkeypatch.setenv("THINKING_SHOW_ELAPSED", "false")
        cfg = BotConfig()
        assert cfg.thinking_show_elapsed is False


class TestAIConfig:
    def test_default_backend(self):
        cfg = AIConfig()
        assert cfg.ai_cli == "copilot"

    def test_codex_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = AIConfig()
        assert cfg.ai_cli == "codex"
        assert cfg.codex.openai_api_key == "sk-test"

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


class TestSecretValues:
    def test_telegram_config_secret_values_with_token(self):
        cfg = TelegramConfig(TG_BOT_TOKEN="my-bot-token-12345678")
        assert "my-bot-token-12345678" in cfg.secret_values()

    def test_telegram_config_secret_values_empty(self):
        cfg = TelegramConfig()
        assert cfg.secret_values() == []

    def test_slack_config_secret_values(self):
        cfg = SlackConfig(slack_bot_token="xoxb-abc", slack_app_token="xapp-xyz")
        assert "xoxb-abc" in cfg.secret_values()
        assert "xapp-xyz" in cfg.secret_values()

    def test_ai_config_secret_values(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-key")
        cfg = AIConfig()
        secrets = cfg.secret_values()
        assert "sk-openai-key" in secrets
        assert "sk-ant-key" in secrets

    def test_ai_config_no_ai_api_key_field(self):
        """AIConfig must not have an ai_api_key field after the refactor."""
        cfg = AIConfig()
        assert not hasattr(cfg, "ai_api_key"), (
            "ai_api_key was removed in v1.1.0 — do not re-add it"
        )

    def test_ai_config_delegates_to_nested_secrets(self, monkeypatch):
        """AIConfig.secret_values() includes values from DirectAIConfig and CodexAIConfig."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-delegated-key")
        cfg = AIConfig()
        assert "sk-delegated-key" in cfg.secret_values()

    def test_direct_config_secret_values(self, monkeypatch):
        """DirectAIConfig.secret_values() returns both openai_api_key and anthropic_api_key."""
        from src.config import DirectAIConfig
        cfg = DirectAIConfig(openai_api_key="sk-oai", anthropic_api_key="sk-ant")
        secrets = cfg.secret_values()
        assert "sk-oai" in secrets
        assert "sk-ant" in secrets

    def test_voice_config_secret_values(self):
        from src.config import VoiceConfig
        cfg = VoiceConfig(whisper_api_key="whisper-secret-key")
        assert "whisper-secret-key" in cfg.secret_values()

    def test_storage_config_secret_values_empty(self):
        from src.config import StorageConfig
        cfg = StorageConfig()
        assert cfg.secret_values() == []

    def test_all_sub_configs_implement_secret_provider(self):
        """All Settings sub-configs must implement SecretProvider — CI enforcement of OQ13."""
        from src.redact import SecretProvider
        from src.config import Settings
        s = Settings()
        for field_name in Settings.model_fields:
            attr = getattr(s, field_name)
            if hasattr(type(attr), "model_fields"):  # it's a sub-config (BaseSettings)
                assert isinstance(attr, SecretProvider), (
                    f"{field_name} ({type(attr).__name__}) does not implement SecretProvider. "
                    "Add a secret_values() -> list[str] method."
                )


class TestStorageConfig:
    def test_defaults(self):
        from src.config import StorageConfig
        cfg = StorageConfig()
        assert cfg.storage_backend == "sqlite"
        assert cfg.audit_backend == "sqlite"

    def test_storage_backend_from_env(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        from src.config import StorageConfig
        cfg = StorageConfig()
        assert cfg.storage_backend == "memory"

    def test_audit_backend_from_env(self, monkeypatch):
        monkeypatch.setenv("AUDIT_BACKEND", "null")
        from src.config import StorageConfig
        cfg = StorageConfig()
        assert cfg.audit_backend == "null"


class TestDeprecationWarnings:
    def test_ai_api_key_deprecation_warning(self, monkeypatch):
        """Setting AI_API_KEY env var triggers DeprecationWarning at Settings.load()."""
        monkeypatch.setenv("AI_API_KEY", "sk-old-key")
        from src.config import Settings
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings.load()
        assert any(issubclass(x.category, DeprecationWarning) and "AI_API_KEY" in str(x.message) for x in w)

    def test_codex_api_key_deprecation_warning(self, monkeypatch):
        """Setting CODEX_API_KEY env var triggers DeprecationWarning at Settings.load()."""
        monkeypatch.setenv("CODEX_API_KEY", "codex-old-key")
        from src.config import Settings
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings.load()
        assert any(issubclass(x.category, DeprecationWarning) and "CODEX_API_KEY" in str(x.message) for x in w)

    def test_no_warning_when_keys_absent(self, monkeypatch):
        """No DeprecationWarning when old vars are not set."""
        from src.config import Settings
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Settings.load()
        dep_msgs = [str(x.message) for x in w if issubclass(x.category, DeprecationWarning)]
        assert not any("AI_API_KEY" in m or "CODEX_API_KEY" in m for m in dep_msgs)


class TestValidateConfig:
    def _slack_settings(self, monkeypatch, **extra_env):
        """Create a settings object with valid Slack platform config."""
        monkeypatch.setenv("PLATFORM", "slack")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "C123")
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)
        from src.config import Settings
        return Settings.load()

    def test_validate_codex_requires_openai_key(self, monkeypatch):
        settings = self._slack_settings(monkeypatch, AI_CLI="codex")
        from src.main import _validate_config
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _validate_config(settings)

    def test_validate_api_openai_requires_key(self, monkeypatch):
        settings = self._slack_settings(monkeypatch, AI_CLI="api", AI_PROVIDER="openai")
        from src.main import _validate_config
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _validate_config(settings)

    def test_validate_api_anthropic_requires_key(self, monkeypatch):
        settings = self._slack_settings(monkeypatch, AI_CLI="api", AI_PROVIDER="anthropic")
        from src.main import _validate_config
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            _validate_config(settings)

    def test_validate_ollama_no_key_needed(self, monkeypatch):
        """AI_CLI=api + AI_PROVIDER=ollama passes validation without any API key."""
        settings = self._slack_settings(monkeypatch, AI_CLI="api", AI_PROVIDER="ollama")
        from src.main import _validate_config
        _validate_config(settings)  # must not raise

    def test_validate_whisper_requires_key(self, monkeypatch):
        settings = self._slack_settings(monkeypatch, WHISPER_PROVIDER="openai")
        from src.main import _validate_config
        with pytest.raises(ValueError, match="WHISPER_API_KEY"):
            _validate_config(settings)


class TestSecretEnvKeys:
    def test_secret_env_keys_correct_names(self):
        """_SECRET_ENV_KEYS must use the actual env var names — wrong names cause token leaks."""
        from src.executor import _SECRET_ENV_KEYS
        # Correct names that must be present
        assert "TG_BOT_TOKEN" in _SECRET_ENV_KEYS
        assert "GITHUB_REPO_TOKEN" in _SECRET_ENV_KEYS
        assert "ANTHROPIC_API_KEY" in _SECRET_ENV_KEYS
        assert "OPENAI_API_KEY" in _SECRET_ENV_KEYS
        assert "GEMINI_API_KEY" in _SECRET_ENV_KEYS
        assert "GOOGLE_API_KEY" in _SECRET_ENV_KEYS
        assert "COPILOT_GITHUB_TOKEN" in _SECRET_ENV_KEYS
        # Wrong names must NOT be present (regressions would cause silent token leaks)
        assert "TELEGRAM_BOT_TOKEN" not in _SECRET_ENV_KEYS
        assert "GITHUB_TOKEN" not in _SECRET_ENV_KEYS
        # Removed vars must not be present
        assert "AI_API_KEY" not in _SECRET_ENV_KEYS
        assert "CODEX_API_KEY" not in _SECRET_ENV_KEYS
