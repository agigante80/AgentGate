import logging
import os
from pathlib import Path

from src.ai.adapter import AICLIBackend
from src.config import AIConfig, CopilotAIConfig, CodexAIConfig, DirectAIConfig, REPO_DIR  # noqa: F401

logger = logging.getLogger(__name__)


def create_backend(ai: AIConfig) -> AICLIBackend:
    if ai.ai_cli == "copilot":
        from src.ai.copilot import CopilotBackend
        return CopilotBackend(
            model=ai.ai_model,
            opts=ai.ai_cli_opts,
            skills_dirs=ai.copilot.copilot_skills_dirs,
        )

    if ai.ai_cli == "codex":
        from src.ai.codex import CodexBackend
        # CODEX_API_KEY / CODEX_MODEL take precedence; fall back to shared AI_API_KEY / AI_MODEL
        codex_key = ai.codex.codex_api_key or ai.ai_api_key
        codex_model = ai.codex.codex_model or ai.ai_model or "o3"
        return CodexBackend(api_key=codex_key, model=codex_model, opts=ai.ai_cli_opts)

    if ai.ai_cli == "api":
        if ai.ai_cli_opts:
            logger.warning(
                "AI_CLI_OPTS is set but AI_CLI=api does not use a subprocess CLI; "
                "the value will be ignored."
            )
        system_prompt = ""
        if ai.direct.system_prompt_file:
            resolved = os.path.realpath(ai.direct.system_prompt_file)
            if Path(resolved).is_relative_to(REPO_DIR.resolve()):
                raise ValueError(
                    f"SYSTEM_PROMPT_FILE must not point inside the cloned repo ({REPO_DIR}). "
                    "Mount it via a separate Docker volume (e.g. /config/system-prompt.md)."
                )
            try:
                system_prompt = Path(resolved).read_text()
            except OSError as exc:
                logger.warning("Could not read SYSTEM_PROMPT_FILE %r: %s", ai.direct.system_prompt_file, exc)
        from src.ai.direct import DirectAPIBackend
        return DirectAPIBackend(
            provider=ai.direct.ai_provider,
            api_key=ai.ai_api_key,
            model=ai.ai_model,
            base_url=ai.direct.ai_base_url,
            system_prompt=system_prompt,
        )

    raise ValueError(f"Unknown AI_CLI value: {ai.ai_cli!r}")
