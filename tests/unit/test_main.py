"""Unit tests for src/main.py private functions."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.main import _read_version, _log_startup_banner, _validate_config, main
from src.config import Settings, TelegramConfig, SlackConfig, BotConfig, AIConfig, GitHubConfig


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
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = "api"
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
    s.github = gh
    s.log = log
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

async def test_startup_calls_slack_branch():
    """startup() routes to _startup_slack when platform=slack (lines 129-133)."""
    from src.main import startup

    settings = _make_settings(platform="slack")
    settings.github = MagicMock()
    settings.github.github_repo_token = "gh-token"
    settings.github.github_repo = "owner/repo"
    settings.github.branch = "main"
    settings.ai = MagicMock()
    settings.ai.ai_cli = "api"

    with patch("src.main.repo.clone", new=AsyncMock()), \
         patch("src.main.repo.configure_git_auth", new=AsyncMock()), \
         patch("src.main.runtime.install_deps", new=AsyncMock(return_value="ok")), \
         patch("src.main.history.init_db", new=AsyncMock()), \
         patch("src.main.create_backend", return_value=MagicMock()), \
         patch("src.main._startup_slack", new=AsyncMock()) as mock_slack, \
         patch("src.main._startup_telegram", new=AsyncMock()) as mock_tg:
        await startup(settings)

    mock_slack.assert_awaited_once()
    mock_tg.assert_not_awaited()


async def test_startup_calls_telegram_branch():
    """startup() routes to _startup_telegram when platform=telegram (lines 129-133)."""
    from src.main import startup

    settings = _make_settings(platform="telegram")
    settings.github = MagicMock()
    settings.github.github_repo_token = "gh-token"
    settings.github.github_repo = "owner/repo"
    settings.github.branch = "main"
    settings.ai = MagicMock()
    settings.ai.ai_cli = "api"

    with patch("src.main.repo.clone", new=AsyncMock()), \
         patch("src.main.repo.configure_git_auth", new=AsyncMock()), \
         patch("src.main.runtime.install_deps", new=AsyncMock(return_value="ok")), \
         patch("src.main.history.init_db", new=AsyncMock()), \
         patch("src.main.create_backend", return_value=MagicMock()), \
         patch("src.main._startup_slack", new=AsyncMock()) as mock_slack, \
         patch("src.main._startup_telegram", new=AsyncMock()) as mock_tg:
        await startup(settings)

    mock_tg.assert_awaited_once()
    mock_slack.assert_not_awaited()
