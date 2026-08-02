import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from agenttoolkit.skills import Skills
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.models import Tool, ToolEffect

logger = logging.getLogger(__name__)

type ToolPredicate = Callable[[Tool], bool]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    raw_args: dict[str, Any]
    context: ToolContext | None = None
    tool: Tool | None = None
    params: BaseModel | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[object]]


class ToolMiddleware:
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        raise NotImplementedError


class ErrorBoundaryMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        try:
            return await next(call)
        except Exception as error:
            logger.exception("Tool '%s' failed", call.name)
            return f"Tool failed: {error}"


class ToolResolutionMiddleware(ToolMiddleware):
    def __init__(
        self,
        tools: Mapping[str, Tool],
    ) -> None:
        self._tools = tools

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        tool = self._tools.get(call.name)
        if tool is None or not tool.is_available(call.context):
            available = [
                name
                for name, candidate in self._tools.items()
                if candidate.is_available(call.context)
            ]
            raise LookupError(f"Unknown tool '{call.name}'. Available: {available}")
        return await next(replace(call, tool=tool))


class ParamValidationMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        if call.tool is None:
            raise RuntimeError("Tool resolution must run before validation")
        params = call.tool.input_model.model_validate(call.raw_args)
        return await next(replace(call, params=params))


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        logger.info("[tool] %s called with arguments: %r", call.name, call.raw_args)
        started = time.perf_counter()
        try:
            return await next(call)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("[tool] %s finished (%.0f ms)", call.name, elapsed_ms)


def _writes_workspace(tool: Tool) -> bool:
    return tool.has_effect(ToolEffect.WRITES_WORKSPACE)


class SkillRefreshMiddleware(ToolMiddleware):
    def __init__(self, *, when: ToolPredicate = _writes_workspace) -> None:
        self._when = when

    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        try:
            return await next(call)
        finally:
            if call.tool is not None and self._when(call.tool):
                skills = None if call.context is None else call.context.resolve(Skills)
                if skills is not None:
                    try:
                        skills.refresh_if_changed()
                    except ValueError:
                        logger.exception(
                            "Skill refresh failed after tool '%s'; "
                            "keeping the active registry.",
                            call.name,
                        )


def compose(
    middlewares: Sequence[ToolMiddleware],
    handler: ToolHandler,
) -> ToolHandler:
    for middleware in reversed(middlewares):
        handler = _wrap(middleware, handler)
    return handler


def default_chain(
    tools: Mapping[str, Tool],
    inner: Sequence[ToolMiddleware] | None = None,
) -> tuple[ToolMiddleware, ...]:
    """Custom middleware runs inside the core so that `call.tool` and
    `call.params` are already populated — filtering on tool metadata is only
    possible after resolution.
    """
    return (
        ErrorBoundaryMiddleware(),
        ToolResolutionMiddleware(tools),
        ParamValidationMiddleware(),
        *(inner or ()),
        CallLoggingMiddleware(),
    )


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> object:
        return await middleware(call, next_handler)

    return handler
