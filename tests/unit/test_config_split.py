"""Unit tests for AIConfig split — sub-config isolation and fallback logic (feature 1.4)."""
import os
import pytest
from unittest.mock import patch, MagicMock

from src.config import AIConfig, CopilotAIConfig, CodexAIConfig, DirectAIConfig


# ── Sub-config env var reading ─────────────────────────────────────────────────

class TestSubConfigEnvReading:
    def test_copilot_sub_config_reads_skills_dirs(self, monkeypatch):
        monkeypatch.setenv("COPILOT_SKILLS_DIRS", "/skills/dev,/skills/shared")
        cfg = CopilotAIConfig()
        assert cfg.copilot_skills_dirs == "/skills/dev,/skills/shared"

    def test_codex_sub_config_reads_api_key(self, monkeypatch):
        monkeypatch.setenv("CODEX_API_KEY", "codex-secret-key")
        cfg = CodexAIConfig()
        assert cfg.codex_api_key == "codex-secret-key"

    def test_codex_sub_config_reads_model(self, monkeypatch):
        monkeypatch.setenv("CODEX_MODEL", "o3-mini")
        cfg = CodexAIConfig()
        assert cfg.codex_model == "o3-mini"

    def test_direct_sub_config_reads_provider(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        cfg = DirectAIConfig()
        assert cfg.ai_provider == "anthropic"

    def test_direct_sub_config_reads_base_url(self, monkeypatch):
        monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434")
        cfg = DirectAIConfig()
        assert cfg.ai_base_url == "http://localhost:11434"

    def test_direct_sub_config_reads_system_prompt_file(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_PROMPT_FILE", "/skills/sec-agent.md")
        cfg = DirectAIConfig()
        assert cfg.system_prompt_file == "/skills/sec-agent.md"


# ── AIConfig shared fields remain at top level ────────────────────────────────

class TestAIConfigSharedFields:
    def test_ai_api_key_at_top_level(self, monkeypatch):
        monkeypatch.setenv("AI_API_KEY", "shared-key")
        cfg = AIConfig()
        assert cfg.ai_api_key == "shared-key"

    def test_ai_model_at_top_level(self, monkeypatch):
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        cfg = AIConfig()
        assert cfg.ai_model == "gpt-4o"

    def test_ai_cli_at_top_level(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "codex")
        cfg = AIConfig()
        assert cfg.ai_cli == "codex"

    def test_ai_cli_opts_at_top_level(self, monkeypatch):
        monkeypatch.setenv("AI_CLI_OPTS", "--verbose")
        cfg = AIConfig()
        assert cfg.ai_cli_opts == "--verbose"

    def test_sub_configs_accessible(self):
        cfg = AIConfig()
        assert isinstance(cfg.copilot, CopilotAIConfig)
        assert isinstance(cfg.codex, CodexAIConfig)
        assert isinstance(cfg.direct, DirectAIConfig)


# ── Codex fallback logic ───────────────────────────────────────────────────────

class TestCodexFallback:
    def test_codex_uses_specific_api_key_when_set(self, monkeypatch):
        """CODEX_API_KEY takes precedence over AI_API_KEY."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("CODEX_API_KEY", "codex-specific-key")
        monkeypatch.setenv("AI_API_KEY", "shared-key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "codex-specific-key"

    def test_codex_falls_back_to_shared_api_key(self, monkeypatch):
        """When CODEX_API_KEY is empty, falls back to AI_API_KEY."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.delenv("CODEX_API_KEY", raising=False)
        monkeypatch.setenv("AI_API_KEY", "shared-key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "shared-key"

    def test_codex_uses_specific_model_when_set(self, monkeypatch):
        """CODEX_MODEL takes precedence over AI_MODEL."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("CODEX_MODEL", "o3-mini")
        monkeypatch.setenv("AI_MODEL", "o4")
        monkeypatch.setenv("AI_API_KEY", "key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o3-mini"

    def test_codex_falls_back_to_shared_model(self, monkeypatch):
        """When CODEX_MODEL is empty, falls back to AI_MODEL."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.delenv("CODEX_MODEL", raising=False)
        monkeypatch.setenv("AI_MODEL", "o4")
        monkeypatch.setenv("AI_API_KEY", "key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o4"

    def test_codex_defaults_model_to_o3(self, monkeypatch):
        """When both CODEX_MODEL and AI_MODEL are empty, defaults to 'o3'."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.delenv("CODEX_MODEL", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.setenv("AI_API_KEY", "key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o3"


# ── Subprocess env isolation ───────────────────────────────────────────────────

class TestSubprocessEnvIsolation:
    def test_copilot_subprocess_env_does_not_inject_openai_key_from_config(self, monkeypatch):
        """CopilotBackend should not inject OPENAI_API_KEY unless it was already in os.environ."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("AI_API_KEY", "shared-key")
        monkeypatch.setenv("COPILOT_SKILLS_DIRS", "")

        from src.ai.copilot import CopilotBackend
        with patch("src.ai.copilot.CopilotSession"):
            backend = CopilotBackend(model="", opts="", skills_dirs="")

        assert "OPENAI_API_KEY" not in backend._env

    def test_copilot_subprocess_env_does_not_set_codex_model(self, monkeypatch):
        """CopilotBackend must not inject CODEX_MODEL from config into the subprocess env."""
        monkeypatch.delenv("CODEX_MODEL", raising=False)

        from src.ai.copilot import CopilotBackend
        with patch("src.ai.copilot.CopilotSession"):
            backend = CopilotBackend(model="gpt-4o", opts="", skills_dirs="")

        assert "CODEX_MODEL" not in backend._env

    def test_codex_subprocess_env_sets_openai_key(self, monkeypatch):
        """CodexBackend must inject OPENAI_API_KEY in its subprocess env."""
        from src.ai.codex import CodexBackend
        backend = CodexBackend(api_key="codex-only-key", model="o3", opts="")
        _, env = backend._make_cmd("hello")
        assert env["OPENAI_API_KEY"] == "codex-only-key"

    def test_codex_subprocess_env_does_not_set_copilot_skills_dirs(self, monkeypatch):
        """CodexBackend subprocess env must not inject COPILOT_SKILLS_DIRS from config."""
        monkeypatch.delenv("COPILOT_SKILLS_DIRS", raising=False)

        from src.ai.codex import CodexBackend
        backend = CodexBackend(api_key="key", model="o3", opts="")
        _, env = backend._make_cmd("hello")
        assert "COPILOT_SKILLS_DIRS" not in env

    def test_copilot_sets_copilot_model_when_provided(self, monkeypatch):
        """CopilotBackend sets COPILOT_MODEL in subprocess env when model is given."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from src.ai.copilot import CopilotBackend
        with patch("src.ai.copilot.CopilotSession"):
            backend = CopilotBackend(model="gpt-4o", opts="", skills_dirs="")

        assert backend._env.get("COPILOT_MODEL") == "gpt-4o"

    def test_copilot_sets_skills_dirs_in_env(self, monkeypatch):
        """CopilotBackend sets COPILOT_SKILLS_DIRS in subprocess env when skills_dirs is given."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from src.ai.copilot import CopilotBackend
        with patch("src.ai.copilot.CopilotSession"):
            backend = CopilotBackend(model="", opts="", skills_dirs="/tmp/skills")

        assert backend._env.get("COPILOT_SKILLS_DIRS") == "/tmp/skills"


# ── Factory path validation ────────────────────────────────────────────────────

class TestFactoryPaths:
    def test_factory_copilot_uses_sub_config_skills_dirs(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "copilot")
        monkeypatch.setenv("COPILOT_SKILLS_DIRS", "/my/skills")
        from src.ai.factory import create_backend
        from src.ai.copilot import CopilotBackend
        cfg = AIConfig()
        with patch("src.ai.copilot.CopilotSession") as MockSession:
            backend = create_backend(cfg)
        assert isinstance(backend, CopilotBackend)
        assert backend._env.get("COPILOT_SKILLS_DIRS") == "/my/skills"

    def test_factory_direct_uses_sub_config_provider(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AI_API_KEY", "ant-key")
        monkeypatch.setenv("AI_MODEL", "claude-3-5-sonnet-20241022")
        from src.ai.factory import create_backend
        from src.ai.direct import DirectAPIBackend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)
        assert backend._provider == "anthropic"

    def test_factory_direct_uses_shared_api_key(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "shared-openai-key")
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "shared-openai-key"


# ── SecretRedactor coverage ────────────────────────────────────────────────────

class TestRedactorCoverage:
    def test_redactor_collects_codex_api_key(self):
        """CODEX_API_KEY must be in the redactor's known-values list."""
        from src.redact import SecretRedactor

        s = MagicMock()
        s.bot.allow_secrets = False
        s.telegram.bot_token = ""
        s.slack.slack_bot_token = ""
        s.slack.slack_app_token = ""
        s.github.github_repo_token = ""
        s.ai.ai_api_key = "shared-key-value-long"
        s.ai.codex.codex_api_key = "codex-only-secret-key"
        s.voice.whisper_api_key = ""

        redactor = SecretRedactor(s)
        assert "codex-only-secret-key" not in redactor.redact(
            "The key is codex-only-secret-key"
        )
