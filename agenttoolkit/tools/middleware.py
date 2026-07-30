import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from agenttoolkit.skills import Skills
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.models import Tool, ToolEffect
from agenttoolkit.tools.results import ActionResult

logger = logging.getLogger(__name__)

type ToolPredicate = Callable[[Tool], bool]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    raw_args: dict[str, Any]
    context: ToolContext | None = None
    tool: Tool | None = None
    params: BaseModel | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[ActionResult[object]]]


class ToolMiddleware:
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        raise NotImplementedError


class ErrorBoundaryMiddleware(ToolMiddleware):
    def __init__(self, result_type: type[ActionResult[object]]) -> None:
        self._result_type = result_type

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        try:
            return await next(call)
        except Exception:
            logger.exception("Tool '%s' failed", call.name)
            return self._result_type.fail("Internal tool error.")


class ToolResolutionMiddleware(ToolMiddleware):
    def __init__(
        self,
        tools: Mapping[str, Tool],
        result_type: type[ActionResult[object]],
    ) -> None:
        self._tools = tools
        self._result_type = result_type

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        tool = self._tools.get(call.name)
        if tool is None or not tool.is_available(call.context):
            available = [
                name
                for name, candidate in self._tools.items()
                if candidate.is_available(call.context)
            ]
            return self._result_type.fail(
                f"Unknown tool '{call.name}'. Available: {available}"
            )
        return await next(replace(call, tool=tool))


class ParamValidationMiddleware(ToolMiddleware):
    def __init__(self, result_type: type[ActionResult[object]]) -> None:
        self._result_type = result_type

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        if call.tool is None:
            raise RuntimeError("Tool resolution must run before validation")
        try:
            params = call.tool.input_model.model_validate(call.raw_args)
        except ValidationError as error:
            return self._result_type.fail(error)
        return await next(replace(call, params=params))


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        logger.info("[tool] %s called with arguments: %r", call.name, call.raw_args)
        started = time.perf_counter()
        result = await next(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "[tool] %s -> %s (%.0f ms)",
            call.name,
            "ok" if result.ok else "fail",
            elapsed_ms,
        )
        return result


def _writes_workspace(tool: Tool) -> bool:
    return tool.has_effect(ToolEffect.WRITES_WORKSPACE)


class SkillRefreshMiddleware(ToolMiddleware):
    """Refresh changed skills after tools that may write skill documents."""

    def __init__(
        self,
        skills: Skills,
        *,
        when: ToolPredicate = _writes_workspace,
    ) -> None:
        self._skills = skills
        self._when = when

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> ActionResult[object]:
        result = await next(call)
        if call.tool is None or not self._when(call.tool):
            return result

        try:
            self._skills.refresh_if_changed()
        except ValueError:
            logger.exception(
                "Skill refresh failed after tool '%s'; keeping the active registry.",
                call.name,
            )
        return result


def compose(
    middlewares: Sequence[ToolMiddleware],
    handler: ToolHandler,
) -> ToolHandler:
    for middleware in reversed(middlewares):
        handler = _wrap(middleware, handler)
    return handler


def default_chain(
    tools: Mapping[str, Tool],
    result_type: type[ActionResult[object]],
    inner: Sequence[ToolMiddleware] | None = None,
) -> tuple[ToolMiddleware, ...]:
    """Custom middleware runs inside the core so that `call.tool` and
    `call.params` are already populated — filtering on tool metadata is only
    possible after resolution.
    """
    return (
        ErrorBoundaryMiddleware(result_type),
        ToolResolutionMiddleware(tools, result_type),
        ParamValidationMiddleware(result_type),
        *(inner or ()),
        CallLoggingMiddleware(),
    )


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> ActionResult[object]:
        return await middleware(call, next_handler)

    return handler
