import logging

from src.ai.adapter import AICLIBackend
from src.config import AIConfig

logger = logging.getLogger(__name__)


def create_backend(ai: AIConfig) -> AICLIBackend:
    if ai.ai_cli == "copilot":
        from src.ai.copilot import CopilotBackend
        return CopilotBackend(model=ai.ai_model, opts=ai.ai_cli_opts)

    if ai.ai_cli == "codex":
        from src.ai.codex import CodexBackend
        return CodexBackend(api_key=ai.ai_api_key, model=ai.ai_model or "o3", opts=ai.ai_cli_opts)

    if ai.ai_cli == "api":
        if ai.ai_cli_opts:
            logger.warning(
                "AI_CLI_OPTS is set but AI_CLI=api does not use a subprocess CLI; "
                "the value will be ignored."
            )
        from src.ai.direct import DirectAPIBackend
        return DirectAPIBackend(
            provider=ai.ai_provider,
            api_key=ai.ai_api_key,
            model=ai.ai_model,
            base_url=ai.ai_base_url,
        )

    raise ValueError(f"Unknown AI_CLI value: {ai.ai_cli!r}")
