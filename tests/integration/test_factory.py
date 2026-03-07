"""Integration tests — AI backend factory."""
import pytest
from unittest.mock import patch, MagicMock

from src.config import AIConfig
from src.ai.factory import create_backend
from src.ai.copilot import CopilotBackend
from src.ai.codex import CodexBackend
from src.ai.direct import DirectAPIBackend


class TestBackendFactory:
    def test_creates_copilot_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "copilot")
        cfg = AIConfig()
        with patch("src.ai.copilot.CopilotSession"):  # patch where it's used
            backend = create_backend(cfg)
        assert isinstance(backend, CopilotBackend)

    def test_creates_codex_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, CodexBackend)

    def test_creates_direct_openai_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)

    def test_creates_direct_anthropic_backend(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AI_API_KEY", "sk-ant-test")
        monkeypatch.setenv("AI_MODEL", "claude-3-5-sonnet-20241022")
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "copilot")  # valid for pydantic
        cfg = AIConfig()
        cfg.__dict__["ai_cli"] = "invalid"  # bypass pydantic for this test
        with pytest.raises(ValueError, match="Unknown AI_CLI"):
            create_backend(cfg)

    def test_copilot_model_passed_through(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "copilot")
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        cfg = AIConfig()
        # Patch where CopilotSession is used, not where it's defined
        with patch("src.ai.copilot.CopilotSession") as MockSession:
            backend = create_backend(cfg)
        MockSession.assert_called_once_with(model="gpt-4o", env=MockSession.call_args[1]["env"], opts="")
        assert cfg.ai_model == "gpt-4o"

    def test_codex_model_passed_through(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("AI_MODEL", "o4")
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o4"
