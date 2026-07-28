import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.results import ActionResult
from agenttoolkit.tools.tool import Tool

logger = logging.getLogger(__name__)


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
    core = (
        ErrorBoundaryMiddleware(result_type),
        ToolResolutionMiddleware(tools, result_type),
        ParamValidationMiddleware(result_type),
    )
    if inner is not None:
        return (*inner, *core)
    return (
        *core,
        CallLoggingMiddleware(),
    )


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> ActionResult[object]:
        return await middleware(call, next_handler)

    return handler
