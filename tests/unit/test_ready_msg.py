"""Unit tests for src/ready_msg.py."""
from unittest.mock import MagicMock

from src.ready_msg import ai_label, build_ready_message
from src.config import Settings, AIConfig, BotConfig, GitHubConfig, DirectAIConfig


def _make_settings(cli="api", provider="openai", model="gpt-4o", image_tag=""):
    s = MagicMock(spec=Settings)
    ai = MagicMock(spec=AIConfig)
    ai.ai_cli = cli
    ai.ai_model = model
    direct = MagicMock(spec=DirectAIConfig)
    direct.ai_provider = provider
    ai.direct = direct
    bot = MagicMock(spec=BotConfig)
    bot.image_tag = image_tag
    gh = MagicMock(spec=GitHubConfig)
    gh.github_repo = "owner/repo"
    gh.branch = "main"
    s.ai = ai
    s.bot = bot
    s.github = gh
    return s


class TestAiLabel:
    def test_api_with_provider_and_model(self):
        s = _make_settings(cli="api", provider="openai", model="gpt-4o")
        assert ai_label(s) == "api/openai (gpt-4o)"

    def test_non_api_cli_uses_cli_name(self):
        s = _make_settings(cli="copilot", provider="", model="")
        assert ai_label(s) == "copilot"

    def test_non_api_cli_with_model(self):
        s = _make_settings(cli="codex", provider="", model="o3")
        assert ai_label(s) == "codex (o3)"

    def test_api_without_provider(self):
        s = _make_settings(cli="api", provider="", model="")
        assert ai_label(s) == "api"


class TestBuildReadyMessage:
    def test_basic_message_contains_key_fields(self):
        s = _make_settings(image_tag="")
        msg = build_ready_message(s, "1.0.0", "gate")
        assert "AgentGate Ready" in msg
        assert "v1.0.0" in msg
        assert "owner/repo" in msg
        assert "/gate help" in msg

    def test_image_tag_included_when_set(self):
        s = _make_settings(image_tag="latest")
        msg = build_ready_message(s, "1.2.3", "gate")
        assert ":latest" in msg
        assert "v1.2.3" in msg

    def test_no_tag_when_image_tag_empty(self):
        s = _make_settings(image_tag="")
        msg = build_ready_message(s, "1.2.3", "gate")
        assert "`:latest`" not in msg
        assert "`:develop`" not in msg
