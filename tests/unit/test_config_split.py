"""Unit tests for AIConfig split — sub-config isolation and per-backend key logic."""
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

    def test_copilot_sub_config_reads_model(self, monkeypatch):
        monkeypatch.setenv("COPILOT_MODEL", "claude-3-5-sonnet")
        cfg = CopilotAIConfig()
        assert cfg.copilot_model == "claude-3-5-sonnet"

    def test_copilot_sub_config_model_defaults_empty(self, monkeypatch):
        monkeypatch.delenv("COPILOT_MODEL", raising=False)
        cfg = CopilotAIConfig()
        assert cfg.copilot_model == ""

    def test_codex_sub_config_reads_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-codex-key")
        cfg = CodexAIConfig()
        assert cfg.openai_api_key == "sk-codex-key"

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

    def test_direct_sub_config_reads_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-direct")
        cfg = DirectAIConfig()
        assert cfg.openai_api_key == "sk-oai-direct"

    def test_direct_sub_config_reads_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-direct")
        cfg = DirectAIConfig()
        assert cfg.anthropic_api_key == "sk-ant-direct"


# ── AIConfig shared fields remain at top level ────────────────────────────────

class TestAIConfigSharedFields:
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

    def test_no_ai_api_key_field(self):
        """ai_api_key was removed in v1.1.0 — AIConfig must not have this field."""
        cfg = AIConfig()
        assert not hasattr(cfg, "ai_api_key")


# ── Codex explicit key ────────────────────────────────────────────────────────

class TestCodexKeyBehavior:
    def test_codex_uses_openai_api_key(self, monkeypatch):
        """Codex backend reads OPENAI_API_KEY directly."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-codex-openai")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "sk-codex-openai"

    def test_codex_raises_without_openai_key(self, monkeypatch):
        """Codex backend raises ValueError when OPENAI_API_KEY is not set."""
        monkeypatch.setenv("AI_CLI", "codex")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            create_backend(cfg)

    def test_codex_uses_specific_model_when_set(self, monkeypatch):
        """CODEX_MODEL takes precedence over AI_MODEL."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.setenv("CODEX_MODEL", "o3-mini")
        monkeypatch.setenv("AI_MODEL", "o4")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o3-mini"

    def test_codex_falls_back_to_shared_model(self, monkeypatch):
        """When CODEX_MODEL is empty, falls back to AI_MODEL."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.delenv("CODEX_MODEL", raising=False)
        monkeypatch.setenv("AI_MODEL", "o4")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o4"

    def test_codex_defaults_model_to_o3(self, monkeypatch):
        """When both CODEX_MODEL and AI_MODEL are empty, defaults to 'o3'."""
        monkeypatch.setenv("AI_CLI", "codex")
        monkeypatch.delenv("CODEX_MODEL", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._model == "o3"


# ── Subprocess env isolation ───────────────────────────────────────────────────

class TestSubprocessEnvIsolation:
    def test_copilot_subprocess_env_does_not_inject_openai_key_from_config(self, monkeypatch):
        """CopilotBackend should not inject OPENAI_API_KEY unless it was already in os.environ."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-key")
        monkeypatch.setenv("AI_MODEL", "claude-3-5-sonnet-20241022")
        from src.ai.factory import create_backend
        from src.ai.direct import DirectAPIBackend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert isinstance(backend, DirectAPIBackend)
        assert backend._provider == "anthropic"

    def test_factory_direct_uses_openai_key_for_openai(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
        monkeypatch.setenv("AI_MODEL", "gpt-4o")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "sk-openai-key"

    def test_factory_direct_uses_anthropic_key_for_anthropic(self, monkeypatch):
        monkeypatch.setenv("AI_CLI", "api")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-val")
        from src.ai.factory import create_backend
        cfg = AIConfig()
        backend = create_backend(cfg)
        assert backend._api_key == "sk-ant-val"


# ── SecretRedactor coverage ────────────────────────────────────────────────────

class TestRedactorCoverage:
    def test_redactor_collects_openai_api_key(self):
        """OPENAI_API_KEY must be redacted from outgoing text."""
        from src.redact import SecretRedactor

        s = MagicMock()
        s.bot.allow_secrets = False
        s.telegram.bot_token = ""
        s.slack.slack_bot_token = ""
        s.slack.slack_app_token = ""
        s.github.github_repo_token = ""
        s.ai.secret_values.return_value = ["sk-secret-openai-key"]
        s.voice.whisper_api_key = ""

        redactor = SecretRedactor(s)
        assert "sk-secret-openai-key" not in redactor.redact(
            "The key is sk-secret-openai-key"
        )

    def test_redactor_collects_anthropic_key(self):
        """ANTHROPIC_API_KEY must be redacted from outgoing text."""
        from src.redact import SecretRedactor

        s = MagicMock()
        s.bot.allow_secrets = False
        s.telegram.bot_token = ""
        s.slack.slack_bot_token = ""
        s.slack.slack_app_token = ""
        s.github.github_repo_token = ""
        s.ai.secret_values.return_value = ["sk-ant-secret-anthropic-key"]
        s.voice.whisper_api_key = ""

        redactor = SecretRedactor(s)
        assert "sk-ant-secret-anthropic-key" not in redactor.redact(
            "The key is sk-ant-secret-anthropic-key"
        )
