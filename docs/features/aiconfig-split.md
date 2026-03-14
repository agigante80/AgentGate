# Split AIConfig into Per-Backend Sub-Configs

> Status: **Implemented** (v0.18.0, commit TBD) | Priority: Low (long-term architecture)

## Problem

`src/config.py` `AIConfig` contains fields for Copilot, Codex, and Direct API in a flat struct. Adding a new backend adds noise to every other backend's namespace (e.g., `copilot_model` appears alongside `ai_base_url` even when `AI_CLI=codex`).

## Implementation

Three per-backend sub-config classes live inside `AIConfig`, each isolated to fields that only apply to that backend. Shared fields (`ai_api_key`, `ai_model`, `ai_cli_opts`) remain at the top `AIConfig` level as fallbacks.

```python
class CopilotAIConfig(BaseSettings):
    copilot_model: str = ""        # COPILOT_MODEL — overrides AI_MODEL; empty = use AI_MODEL
    copilot_skills_dirs: str = ""  # COPILOT_SKILLS_DIRS

class CodexAIConfig(BaseSettings):
    codex_api_key: str = ""   # CODEX_API_KEY — falls back to AIConfig.ai_api_key
    codex_model: str = ""     # CODEX_MODEL — falls back to AIConfig.ai_model then "o3"

class DirectAIConfig(BaseSettings):
    system_prompt_file: str = ""   # SYSTEM_PROMPT_FILE
    ai_provider: str = ""          # AI_PROVIDER
    ai_base_url: str = ""          # AI_BASE_URL

class AIConfig(BaseSettings):
    ai_cli: Literal["copilot", "codex", "api"] = "copilot"
    ai_api_key: str = ""           # shared — codex + voice fall back to this
    ai_model: str = ""             # shared — codex and copilot fall back to this
    ai_cli_opts: str = ""
    copilot: CopilotAIConfig = Field(default_factory=CopilotAIConfig)
    codex: CodexAIConfig = Field(default_factory=CodexAIConfig)
    direct: DirectAIConfig = Field(default_factory=DirectAIConfig)
```

## Env Var Precedence

| Backend | Model resolution |
|---------|-----------------|
| `copilot` | `COPILOT_MODEL` → `AI_MODEL` |
| `codex` | `CODEX_MODEL` → `AI_MODEL` → `o3` |
| `api` | `AI_MODEL` (direct) |

All env var names are unchanged from the original flat design. Only internal attribute access paths changed (e.g. `settings.ai.copilot.copilot_skills_dirs`).

## Files Changed

- `src/config.py` — `CopilotAIConfig.copilot_model` added; nested sub-configs in `AIConfig`
- `src/ai/factory.py` — copilot model resolution: `ai.copilot.copilot_model or ai.ai_model`
- `tests/unit/test_config_split.py` — coverage for all sub-config env vars and fallbacks
- `tests/integration/test_factory.py` — `COPILOT_MODEL` override test added
- `README.md` — `COPILOT_MODEL` row added to env var tables

