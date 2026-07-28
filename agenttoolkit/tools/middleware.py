from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from .context import ToolContext
from .results import ActionResult
from .tool import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    raw_args: dict[str, Any]
    context: ToolContext | None = None
    tool: Tool | None = None
    params: BaseModel | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[ActionResult]]


class ToolMiddleware:
    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult:
        raise NotImplementedError


class ToolExecutionError(Exception):
    """An expected failure whose message is safe to return to the agent."""


class ErrorBoundaryMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult:
        try:
            return await next(call)
        except ToolExecutionError as error:
            return ActionResult.fail(error)
        except Exception:
            logger.exception("Tool '%s' failed", call.name)
            return ActionResult.fail("Internal tool error.")


class ToolResolutionMiddleware(ToolMiddleware):
    def __init__(self, tools: Mapping[str, Tool]) -> None:
        self._tools = tools

    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult:
        tool = self._tools.get(call.name)
        if tool is None or not tool.is_available(call.context):
            available = [
                name
                for name, candidate in self._tools.items()
                if candidate.is_available(call.context)
            ]
            return ActionResult.fail(
                f"Unknown tool '{call.name}'. Available: {available}"
            )
        return await next(replace(call, tool=tool))


class ParamValidationMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult:
        if call.tool is None:
            raise RuntimeError("Tool resolution must run before validation")
        try:
            params = call.tool.input_model.model_validate(call.raw_args)
        except ValidationError as error:
            return ActionResult.fail(error)
        return await next(replace(call, params=params))


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult:
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
    inner: Sequence[ToolMiddleware] | None = None,
) -> tuple[ToolMiddleware, ...]:
    return (
        ErrorBoundaryMiddleware(),
        ToolResolutionMiddleware(tools),
        ParamValidationMiddleware(),
        *((CallLoggingMiddleware(),) if inner is None else tuple(inner)),
    )


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> ActionResult:
        return await middleware(call, next_handler)

    return handler
