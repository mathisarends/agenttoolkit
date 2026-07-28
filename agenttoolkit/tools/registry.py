from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, overload

from pydantic import BaseModel

from agenttoolkit.tools.arguments import resolve_arguments
from agenttoolkit.tools.binding import ToolAvailability, ToolDescription
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.middleware import (
    ToolCall,
    ToolMiddleware,
    compose,
    default_chain,
)
from agenttoolkit.tools.results import ActionResult
from agenttoolkit.tools.schema import ToolSchema
from agenttoolkit.tools.tool import (
    ActionKind,
    StatusFormatter,
    Tool,
    ToolMetadata,
    ToolSchemaFormat,
)


class Tools:
    def __init__(
        self,
        *,
        context: ToolContext | None = None,
        middleware: Sequence[ToolMiddleware] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._context = context
        self._handler = compose(default_chain(self._tools, middleware), self._invoke)

    def action(
        self,
        description: str | ToolDescription,
        name: str | None = None,
        *,
        params: type[BaseModel] | None = None,
        result_instruction: str | None = None,
        respond: bool = True,
        status: StatusFormatter | None = None,
        kind: ActionKind | str = ActionKind.GENERIC,
        available_when: ToolAvailability | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Callable:
        def decorator(func: Callable) -> Callable:
            function_name = getattr(func, "__name__", type(func).__name__)
            self.register(
                Tool(
                    name=name or function_name,
                    description=description,
                    fn=func,
                    param_model=params,
                    metadata=ToolMetadata(
                        kind=kind,
                        respond=respond,
                        result_instruction=result_instruction,
                        status=status,
                        tags=frozenset(tags),
                        extra=metadata or {},
                    ),
                    available_when=available_when,
                )
            )
            return func

        return decorator

    def register(self, tool: Tool, *, replace: bool = False) -> Tool:
        if tool.name in self._tools and not replace:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def inject_tool(self, tool: Tool, *, replace: bool = False) -> Tool:
        return self.register(tool, replace=replace)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def set_context(self, context: ToolContext | None) -> None:
        self._context = context

    def available(self, context: ToolContext | None = None) -> list[Tool]:
        active_context = self._context if context is None else context
        return [
            tool for tool in self._tools.values() if tool.is_available(active_context)
        ]

    @overload
    def get_schema(
        self,
        schema_format: ToolSchemaFormat = ToolSchemaFormat.NATIVE,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema]: ...

    @overload
    def get_schema(
        self,
        schema_format: str,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema] | list[dict[str, Any]]: ...

    def get_schema(
        self,
        schema_format: ToolSchemaFormat | str = ToolSchemaFormat.NATIVE,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema] | list[dict[str, Any]]:
        active_context = self._context if context is None else context
        schemas = [
            tool.to_schema(active_context)
            for tool in self._tools.values()
            if tool.is_available(active_context)
        ]
        schema_format = ToolSchemaFormat(schema_format)
        if schema_format is ToolSchemaFormat.OPENAI:
            return [schema.to_openai_schema() for schema in schemas]
        if schema_format is ToolSchemaFormat.ANTHROPIC:
            return [schema.to_anthropic_schema() for schema in schemas]
        return schemas

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> ActionResult:
        return await self._handler(
            ToolCall(
                name=name,
                raw_args=dict(arguments or {}),
                context=self._context if context is None else context,
            )
        )

    def merge(self, other: Tools, *, replace: bool = False) -> None:
        for tool in other:
            self.register(tool, replace=replace)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    async def _invoke(self, call: ToolCall) -> ActionResult:
        if call.tool is None or call.params is None:
            raise RuntimeError("Tool pipeline did not resolve and validate the call")
        arguments = resolve_arguments(call.tool, call.params, call.context)
        result = await call.tool.execute(arguments)
        return (
            result if isinstance(result, ActionResult) else ActionResult.success(result)
        )
