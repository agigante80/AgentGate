"""Unit tests for src/main.py private functions."""
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import _read_version, _log_startup_banner, _validate_config, _ensure_claude_settings, main
from src.config import Settings, TelegramConfig, SlackConfig, BotConfig, AIConfig, GitHubConfig, AuditConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_settings(platform="telegram", bot_token="abc:token", chat_id="99999",
                   slack_bot_token="xoxb-test", slack_app_token="xapp-test",
                   slack_channel_id="C12345TEST"):
    s = MagicMock(spec=Settings)
    s.platform = platform
    tg = MagicMock(spec=TelegramConfig)
    tg.bot_token = bot_token
    tg.chat_id = chat_id
    slack = MagicMock(spec=SlackConfig)
    slack.slack_bot_token = slack_bot_token
    slack.slack_app_token = slack_app_token
    slack.slack_channel_id = slack_channel_id
    bot = MagicMock(spec=BotConfig)
    bot.bot_cmd_prefix = "gate"
    bot.history_turns = 10
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = "copilot"  # no key check for copilot
    ai.codex = MagicMock()
    ai.codex.openai_api_key = ""
    ai.direct = MagicMock()
    ai.direct.ai_provider = ""
    ai.direct.openai_api_key = ""
    ai.direct.anthropic_api_key = ""
    voice = MagicMock()
    voice.whisper_provider = "none"
    voice.whisper_api_key = ""
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    log = MagicMock()
    log.log_level = "INFO"
    log.log_dir = ""
    s.telegram = tg
    s.slack = slack
    s.bot = bot
    s.ai = ai
    s.voice = voice
    s.github = gh
    s.log = log
    audit = MagicMock(spec=AuditConfig)
    audit.audit_enabled = True
    s.audit = audit
    return s


# ── _read_version ─────────────────────────────────────────────────────────────

def test_read_version_returns_version_string():
    v = _read_version()
    assert isinstance(v, str)
    assert len(v) > 0


def test_read_version_oserror_returns_unknown(tmp_path):
    """When the VERSION file is unreadable, _read_version returns 'unknown'."""
    with patch("src.main._VERSION_FILE") as mock_path:
        mock_path.read_text.side_effect = OSError("no file")
        result = _read_version()
    assert result == "unknown"


# ── _log_startup_banner ───────────────────────────────────────────────────────

def test_log_startup_banner_no_crash():
    """_log_startup_banner should log without raising."""
    settings = _make_settings()
    _log_startup_banner(settings, "1.2.3")  # must not raise


# ── _validate_config ──────────────────────────────────────────────────────────

class TestValidateConfig:
    def test_telegram_missing_token_raises(self):
        s = _make_settings(platform="telegram", bot_token="")
        with pytest.raises(ValueError, match="TG_BOT_TOKEN"):
            _validate_config(s)

    def test_telegram_missing_chat_id_raises(self):
        s = _make_settings(platform="telegram", chat_id="")
        with pytest.raises(ValueError, match="TG_CHAT_ID"):
            _validate_config(s)

    def test_telegram_valid_no_exception(self):
        s = _make_settings(platform="telegram", bot_token="abc:token", chat_id="123")
        _validate_config(s)  # must not raise

    def test_slack_missing_bot_token_raises(self):
        s = _make_settings(platform="slack", slack_bot_token="")
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            _validate_config(s)

    def test_slack_missing_app_token_raises(self):
        s = _make_settings(platform="slack", slack_app_token="")
        with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
            _validate_config(s)

    def test_slack_valid_no_exception(self):
        s = _make_settings(platform="slack", slack_bot_token="xoxb-test", slack_app_token="xapp-test")
        _validate_config(s)  # must not raise

    def test_slack_missing_channel_id_raises(self):
        s = _make_settings(platform="slack", slack_channel_id="")
        with pytest.raises(ValueError, match="SLACK_CHANNEL_ID"):
            _validate_config(s)


# ── main() error path ─────────────────────────────────────────────────────────

def test_main_config_error_calls_sys_exit():
    """When Settings.load() raises, main() calls sys.exit(1)."""
    with patch("src.main.Settings.load", side_effect=ValueError("bad config")):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def test_main_success_path_handles_keyboard_interrupt():
    """main() handles KeyboardInterrupt from asyncio.run gracefully (lines 147-153)."""
    settings = _make_settings()
    with patch("src.main.Settings.load", return_value=settings), \
         patch("src.main._validate_config"), \
         patch("src.main.configure_logging"), \
         patch("src.main._log_startup_banner"), \
         patch("src.main.asyncio.run", side_effect=KeyboardInterrupt()):
        main()  # must not raise


# ── startup() platform branch ─────────────────────────────────────────────────

# ── _ensure_claude_settings ───────────────────────────────────────────────────

class TestEnsureClaudeSettings:
    async def test_skips_non_claude_backend(self, tmp_path):
        with patch("src.main.REPO_DIR", tmp_path):
            await _ensure_claude_settings("copilot")
        assert not (tmp_path / ".claude" / "settings.json").exists()

    async def test_creates_settings_when_missing(self, tmp_path):
        with patch("src.main.REPO_DIR", tmp_path):
            await _ensure_claude_settings("claude")
        settings_file = tmp_path / ".claude" / "settings.json"
        assert settings_file.exists()
        content = json.loads(settings_file.read_text())
        assert "permissions" in content
        assert content["permissions"]["deny"] == []
        assert len(content["permissions"]["allow"]) > 0

    async def test_does_not_overwrite_existing(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text('{"custom": true}')
        with patch("src.main.REPO_DIR", tmp_path):
            await _ensure_claude_settings("claude")
        assert json.loads(settings_file.read_text()) == {"custom": True}

    async def test_handles_permission_error(self, tmp_path):
        read_only = tmp_path / "readonly"
        read_only.mkdir()
        read_only.chmod(0o444)
        with patch("src.main.REPO_DIR", read_only):
            await _ensure_claude_settings("claude")  # must not raise
        read_only.chmod(0o755)  # cleanup


async def test_startup_calls_slack_branch():
    """startup() routes to slack adapter when platform=slack."""
    from src.main import startup
    from src.config import StorageConfig

    settings = _make_settings(platform="slack")
    settings.github = MagicMock()
    settings.github.github_repo_token = "gh-token"
    settings.github.github_repo = "owner/repo"
    settings.github.branch = "main"
    settings.ai = MagicMock()
    settings.ai.ai_cli = "api"
    settings.bot = MagicMock(spec=BotConfig)
    settings.bot.max_output_chars = 3000
    settings.bot.allow_secrets = False
    settings.bot.shell_allowlist = []
    settings.bot.shell_readonly = False
    storage_cfg = MagicMock(spec=StorageConfig)
    storage_cfg.storage_backend = "sqlite"
    storage_cfg.audit_backend = "sqlite"
    settings.storage = storage_cfg

    mock_adapter = AsyncMock()
    mock_adapter.start = AsyncMock()

    with patch("src.repo.clone", new=AsyncMock()), \
         patch("src.repo.configure_git_auth", new=AsyncMock()), \
         patch("src.main.runtime.install_deps", new=AsyncMock(return_value="ok")), \
         patch("src.registry.storage_registry.create", return_value=MagicMock(init=AsyncMock())), \
         patch("src.registry.audit_registry.create", return_value=MagicMock(init=AsyncMock(), verify=AsyncMock(return_value=True))), \
         patch("src.main.create_backend", return_value=MagicMock()), \
         patch("src.main._load_platforms"), \
         patch("src.registry.platform_registry.create", return_value=mock_adapter) as mock_create:
        await startup(settings)

    # Verify the slack platform adapter was created
    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "slack"
    mock_adapter.start.assert_awaited_once()


async def test_startup_calls_telegram_branch():
    """startup() routes to telegram adapter when platform=telegram."""
    from src.main import startup
    from src.config import StorageConfig

    settings = _make_settings(platform="telegram")
    settings.github = MagicMock()
    settings.github.github_repo_token = "gh-token"
    settings.github.github_repo = "owner/repo"
    settings.github.branch = "main"
    settings.ai = MagicMock()
    settings.ai.ai_cli = "api"
    settings.bot = MagicMock(spec=BotConfig)
    settings.bot.max_output_chars = 3000
    settings.bot.allow_secrets = False
    settings.bot.shell_allowlist = []
    settings.bot.shell_readonly = False
    storage_cfg = MagicMock(spec=StorageConfig)
    storage_cfg.storage_backend = "sqlite"
    storage_cfg.audit_backend = "sqlite"
    settings.storage = storage_cfg

    mock_adapter = AsyncMock()
    mock_adapter.start = AsyncMock()

    with patch("src.repo.clone", new=AsyncMock()), \
         patch("src.repo.configure_git_auth", new=AsyncMock()), \
         patch("src.main.runtime.install_deps", new=AsyncMock(return_value="ok")), \
         patch("src.registry.storage_registry.create", return_value=MagicMock(init=AsyncMock())), \
         patch("src.registry.audit_registry.create", return_value=MagicMock(init=AsyncMock(), verify=AsyncMock(return_value=True))), \
         patch("src.main.create_backend", return_value=MagicMock()), \
         patch("src.main._load_platforms"), \
         patch("src.registry.platform_registry.create", return_value=mock_adapter) as mock_create:
        await startup(settings)

    # Verify the telegram platform adapter was created
    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "telegram"
    mock_adapter.start.assert_awaited_once()
