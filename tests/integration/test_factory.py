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
        monkeypatch.delenv("COPILOT_MODEL", raising=False)
        cfg = AIConfig()
        # Patch where CopilotSession is used, not where it's defined
        with patch("src.ai.copilot.CopilotSession") as MockSession:
            backend = create_backend(cfg)
        MockSession.assert_called_once_with(model="gpt-4o", env=MockSession.call_args[1]["env"], opts="")
        assert cfg.ai_model == "gpt-4o"

    def test_copilot_model_overrides_ai_model(self, monkeypatch):
        """COPILOT_MODEL takes precedence over AI_MODEL for the Copilot backend."""
        monkeypatch.setenv("AI_CLI", "copilot")
        monkeypatch.setenv("COPILOT_MODEL", "claude-3-5-sonnet")
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        cfg = AIConfig()
        with patch("src.ai.copilot.CopilotSession") as MockSession:
            backend = create_backend(cfg)
        MockSession.assert_called_once_with(model="claude-3-5-sonnet", env=MockSession.call_args[1]["env"], opts="")

    def test_codex_model_passed_through(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("AI_MODEL", "o4")
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o4"

    def test_api_backend_with_opts_logs_warning(self, monkeypatch, caplog):
        """AI_CLI_OPTS with AI_CLI=api should log a warning (line 21)."""
        import logging
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_CLI_OPTS", "--some-flag")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        cfg = AIConfig()
        with caplog.at_level(logging.WARNING, logger="src.ai.factory"):
            backend = create_backend(cfg)
        assert any("AI_CLI_OPTS" in msg for msg in caplog.messages)
        assert isinstance(backend, DirectAPIBackend)

    def test_api_backend_reads_system_prompt_file(self, monkeypatch, tmp_path):
        """system_prompt_file contents are read and passed to DirectAPIBackend (lines 27-28)."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("You are a helpful assistant.")
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        monkeypatch.setenv("SYSTEM_PROMPT_FILE", str(prompt_file))
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)
        assert backend._system_prompt == "You are a helpful assistant."

    def test_api_backend_system_prompt_file_oserror_logs_warning(self, monkeypatch, caplog):
        """OSError reading system_prompt_file logs a warning and uses empty prompt (lines 29-30)."""
        import logging
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        monkeypatch.setenv("SYSTEM_PROMPT_FILE", "/nonexistent/path/to/prompt.txt")
        cfg = AIConfig()
        with caplog.at_level(logging.WARNING, logger="src.ai.factory"):
            backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)
        assert backend._system_prompt == ""
        assert any("SYSTEM_PROMPT_FILE" in msg for msg in caplog.messages)

    def test_api_backend_system_prompt_file_inside_repo_raises(self, monkeypatch):
        """SYSTEM_PROMPT_FILE pointing inside REPO_DIR must raise ValueError."""
        from src.config import REPO_DIR
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "sk-test")
        # Point to a path inside REPO_DIR
        inside_path = str(REPO_DIR / "some-prompt.md")
        monkeypatch.setenv("SYSTEM_PROMPT_FILE", inside_path)
        cfg = AIConfig()
        with pytest.raises(ValueError, match="SYSTEM_PROMPT_FILE"):
            create_backend(cfg)
