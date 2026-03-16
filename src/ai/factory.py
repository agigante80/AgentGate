import logging
import os
from pathlib import Path

from src.ai.adapter import AICLIBackend
from src.config import AIConfig, REPO_DIR
from src._loader import _module_file_exists

logger = logging.getLogger(__name__)


def _load_backends() -> None:
    """Import each backend module so its @backend_registry.register() decorator fires."""
    import importlib
    import importlib.util

    for mod in ("src.ai.copilot", "src.ai.codex", "src.ai.direct", "src.ai.gemini"):
        rel_path = mod.replace(".", "/") + ".py"
        if importlib.util.find_spec(mod) is None and not _module_file_exists(rel_path):
            continue
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            raise ImportError(
                f"Failed to import backend module '{mod}'. "
                f"Is the required package installed? Original error: {exc}"
            ) from exc


def create_backend(ai: AIConfig) -> AICLIBackend:
    _load_backends()
    from src.registry import backend_registry

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

        provider = ai.direct.ai_provider
        if provider in ("openai", "openai-compat"):
            api_key = ai.direct.openai_api_key
            if not api_key:
                raise ValueError("OPENAI_API_KEY must be set when AI_CLI=api and AI_PROVIDER=openai")
        elif provider == "anthropic":
            api_key = ai.direct.anthropic_api_key
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY must be set when AI_CLI=api and AI_PROVIDER=anthropic")
        else:
            api_key = ""  # ollama or empty provider — no auth needed

        return backend_registry.create(
            "api",
            provider=provider,
            api_key=api_key,
            model=ai.ai_model,
            base_url=ai.direct.ai_base_url,
            system_prompt=system_prompt,
        )

    if ai.ai_cli == "copilot":
        return backend_registry.create(
            "copilot",
            model=ai.copilot.copilot_model or ai.ai_model,
            opts=ai.ai_cli_opts,
            skills_dirs=ai.copilot.copilot_skills_dirs,
            copilot_github_token=ai.copilot.copilot_github_token,
        )

    if ai.ai_cli == "codex":
        codex_key = ai.codex.openai_api_key
        if not codex_key:
            raise ValueError("OPENAI_API_KEY must be set when AI_CLI=codex")
        codex_model = ai.codex.codex_model or ai.ai_model or "o3"
        return backend_registry.create(
            "codex",
            api_key=codex_key,
            model=codex_model,
            opts=ai.ai_cli_opts,
        )

    if ai.ai_cli == "gemini":
        gemini_key = ai.gemini_api_key
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY must be set when AI_CLI=gemini")
        from src.ai.gemini import GeminiBackend
        return GeminiBackend(
            api_key=gemini_key,
            model=ai.ai_model,
            opts=ai.ai_cli_opts,
        )

    raise ValueError(f"Unknown AI_CLI value: {ai.ai_cli!r}")
