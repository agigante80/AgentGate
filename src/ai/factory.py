from src.ai.adapter import AICLIBackend
from src.config import AIConfig


def create_backend(ai: AIConfig) -> AICLIBackend:
    if ai.ai_cli == "copilot":
        from src.ai.copilot import CopilotBackend
        return CopilotBackend(model=ai.copilot_model)

    if ai.ai_cli == "codex":
        from src.ai.codex import CodexBackend
        return CodexBackend(api_key=ai.ai_api_key, model=ai.codex_model)

    if ai.ai_cli == "api":
        from src.ai.direct import DirectAPIBackend
        return DirectAPIBackend(
            provider=ai.ai_provider,
            api_key=ai.ai_api_key,
            model=ai.ai_model,
            base_url=ai.ai_base_url,
        )

    raise ValueError(f"Unknown AI_CLI value: {ai.ai_cli!r}")
