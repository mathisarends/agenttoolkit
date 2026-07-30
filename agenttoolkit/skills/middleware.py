import logging
from collections.abc import Iterable

from agenttoolkit.skills.skills import Skills
from agenttoolkit.tools.middleware import ToolCall, ToolHandler, ToolMiddleware
from agenttoolkit.tools.results import ActionResult

logger = logging.getLogger(__name__)


class SkillRefreshMiddleware(ToolMiddleware):
    """Refresh changed skills after tools that may write skill documents."""

    def __init__(
        self,
        skills: Skills,
        *,
        watched_tools: Iterable[str],
    ) -> None:
        watched = frozenset(watched_tools)
        if not watched:
            raise ValueError("At least one watched tool name is required.")
        self._skills = skills
        self._watched_tools = watched

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        result = await next(call)
        if call.name not in self._watched_tools:
            return result

        try:
            self._skills.refresh_if_changed()
        except ValueError:
            logger.exception(
                "Skill refresh failed after tool '%s'; keeping the active registry.",
                call.name,
            )
        return result
