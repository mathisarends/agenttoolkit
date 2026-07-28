import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.tool import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    raw_args: dict[str, Any]
    context: ToolContext | None = None
    tool: Tool | None = None
    params: BaseModel | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[Any]]


class ToolMiddleware:
    async def __call__(self, call: ToolCall, next: ToolHandler) -> Any:
        raise NotImplementedError


class ErrorBoundaryMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> Any:
        try:
            return await next(call)
        except Exception:
            logger.exception("Tool '%s' failed", call.name)
            raise


class ToolResolutionMiddleware(ToolMiddleware):
    def __init__(self, tools: Mapping[str, Tool]) -> None:
        self._tools = tools

    async def __call__(self, call: ToolCall, next: ToolHandler) -> Any:
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
    async def __call__(self, call: ToolCall, next: ToolHandler) -> Any:
        if call.tool is None:
            raise RuntimeError("Tool resolution must run before validation")
        params = call.tool.input_model.model_validate(call.raw_args)
        return await next(replace(call, params=params))


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> Any:
        logger.info("[tool] %s called with arguments: %r", call.name, call.raw_args)
        started = time.perf_counter()
        result = await next(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info("[tool] %s completed (%.0f ms)", call.name, elapsed_ms)
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
    inner: Sequence[ToolMiddleware] | None = None,
) -> tuple[ToolMiddleware, ...]:
    core = (
        ErrorBoundaryMiddleware(),
        ToolResolutionMiddleware(tools),
        ParamValidationMiddleware(),
    )
    if inner is not None:
        return (*inner, *core)
    return (
        *core,
        CallLoggingMiddleware(),
    )


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> Any:
        return await middleware(call, next_handler)

    return handler
