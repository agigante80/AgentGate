import logging
import os

from src.ai.adapter import AICLIBackend
from src.ai.session import CopilotSession
from src.config import REPO_DIR

logger = logging.getLogger(__name__)


class CopilotBackend(AICLIBackend):
    is_stateful = False  # subprocess -p mode; bot provides history via context
    def __init__(self, model: str = "", opts: str = "", skills_dirs: str = "") -> None:
        self._model = model
        self._opts = opts
        self._env = {**os.environ}
        if model:
            self._env["COPILOT_MODEL"] = model
        if skills_dirs:
            self._env["COPILOT_SKILLS_DIRS"] = skills_dirs
            for d in skills_dirs.split(","):
                resolved = os.path.realpath(d.strip())
                if os.path.realpath(str(REPO_DIR)) in resolved:
                    logger.warning(
                        "COPILOT_SKILLS_DIRS entry %r is inside REPO_DIR (%s) — "
                        "repo contributors can influence agent behaviour via skill files.",
                        d.strip(), REPO_DIR,
                    )
        self._session = CopilotSession(model=model, env=self._env, opts=opts)

    async def send(self, prompt: str) -> str:
        return await self._session.send(prompt)

    def clear_history(self) -> None:
        self._session.close()
        self._session = CopilotSession(model=self._model, env=self._env, opts=self._opts)

    def close(self) -> None:
        self._session.close()
