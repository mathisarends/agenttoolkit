from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, overload

from pydantic import BaseModel, ConfigDict, Field, create_model

from agenttoolkit.tools.arguments import resolve_arguments
from agenttoolkit.tools.binding import ToolAvailability, ToolDescription
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.middleware import (
    ToolCall,
    ToolMiddleware,
    compose,
)
from agenttoolkit.tools.models import (
    StatusFormatter,
    Tool,
    ToolEffect,
    ToolMetadata,
    ToolSchemaFormat,
)
from agenttoolkit.tools.schema import ToolSchema


class Tools:
    def __init__(
        self,
        *,
        context: ToolContext | None = None,
        middleware: Sequence[ToolMiddleware] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._context = context
        self._handler = compose(middleware or (), self._invoke)

    def action[ParamsT: BaseModel, **CallT, ResultT](
        self,
        description: str | ToolDescription,
        name: str | None = None,
        *,
        params: type[ParamsT] | None = None,
        status: StatusFormatter[ParamsT] | None = None,
        effects: Iterable[ToolEffect] = (),
        requires_approval: bool = False,
        available_when: ToolAvailability | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Callable[
        [Callable[CallT, ResultT]],
        Callable[CallT, ResultT],
    ]:
        def decorator(
            func: Callable[CallT, ResultT],
        ) -> Callable[CallT, ResultT]:
            function_name = getattr(func, "__name__", type(func).__name__)
            self._register(
                Tool(
                    name=name or function_name,
                    description=description,
                    fn=func,
                    param_model=params,
                    metadata=ToolMetadata(
                        effects=frozenset(effects),
                        status=status,
                        tags=frozenset(tags),
                        extra=metadata or {},
                    ),
                    requires_approval=requires_approval,
                    available_when=available_when,
                )
            )
            return func

        return decorator

    def _register(self, tool: Tool, *, replace: bool = False) -> Tool:
        if tool.name in self._tools and not replace:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

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

    @overload
    def create_action_model[ModelT: BaseModel](
        self,
        include_actions: Iterable[str] | None = None,
        *,
        base_model: type[ModelT],
        context: ToolContext | None = None,
    ) -> list[type[ModelT]]: ...

    @overload
    def create_action_model(
        self,
        include_actions: Iterable[str] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> list[type[BaseModel]]: ...

    def create_action_model(
        self,
        include_actions: Iterable[str] | None = None,
        *,
        base_model: type[BaseModel] = BaseModel,
        context: ToolContext | None = None,
    ) -> list[type[BaseModel]]:
        """Build one structured-output model per available tool."""
        included = None if include_actions is None else frozenset(include_actions)
        models: list[type[BaseModel]] = []
        active_context = self._context if context is None else context

        for tool in self._tools.values():
            if not tool.is_available(active_context):
                continue
            if included is not None and tool.name not in included:
                continue
            models.append(
                create_model(
                    f"{tool.name.title().replace('_', '')}ActionModel",
                    __base__=base_model,
                    __config__=ConfigDict(extra="forbid"),
                    **{
                        tool.name: (
                            tool.input_model,
                            Field(
                                ...,
                                description=tool.resolve_description(active_context),
                            ),
                        )
                    },
                )
            )

        return models

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> object:
        return await self._handler(
            ToolCall(
                name=name,
                raw_args=dict(arguments or {}),
                context=self._context if context is None else context,
                tool=self._tools.get(name),
            )
        )

    def merge(self, other: "Tools", *, replace: bool = False) -> None:
        for tool in other:
            self._register(tool, replace=replace)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    async def _invoke(self, call: ToolCall) -> object:
        tool = call.tool
        if tool is None or not tool.is_available(call.context):
            available = [
                candidate.name
                for candidate in self._tools.values()
                if candidate.is_available(call.context)
            ]
            raise LookupError(f"Unknown tool '{call.name}'. Available: {available}")

        params = tool.input_model.model_validate(call.raw_args)
        arguments = resolve_arguments(tool, params, call.context)
        return await tool.execute(arguments)
