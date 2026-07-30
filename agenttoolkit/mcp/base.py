from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from agenttoolkit.tools.models import Tool, ToolEffect, ToolMetadata
from agenttoolkit.tools.results import ActionResult
from agenttoolkit.tools.tools import Tools


class _MCPArguments(BaseModel):
    model_config = ConfigDict(extra="allow")


@dataclass(frozen=True, slots=True)
class MCPToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MCPToolPage:
    tools: tuple[MCPToolSpec, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MCPToolRegistration:
    name: str | None = None
    effects: tuple[ToolEffect, ...] = ()
    requires_approval: bool = False
    tags: tuple[str, ...] = ("mcp",)
    metadata: Mapping[str, Any] = field(default_factory=dict)


type MCPToolConfigurator = Callable[
    [MCPToolSpec],
    MCPToolRegistration | None,
]


class MCPClient(ABC):
    @abstractmethod
    async def list_tools(
        self,
        *,
        cursor: str | None = None,
    ) -> MCPToolPage: ...

    @abstractmethod
    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ActionResult[object]: ...

    async def register_tools(
        self,
        tools: Tools,
        *,
        prefix: str = "",
        configure: MCPToolConfigurator | None = None,
        replace: bool = False,
    ) -> list[Tool]:
        definitions: list[MCPToolSpec] = []
        cursor: str | None = None
        while True:
            page = await self.list_tools(cursor=cursor)
            definitions.extend(page.tools)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        configured = [
            (definition, registration)
            for definition in definitions
            if (
                registration := (
                    MCPToolRegistration()
                    if configure is None
                    else configure(definition)
                )
            )
            is not None
        ]
        names = [
            f"{prefix}{registration.name or definition.name}"
            for definition, registration in configured
        ]
        if len(names) != len(set(names)):
            raise ValueError("MCP tool names are not unique after applying the prefix")
        if not replace:
            collisions = [name for name in names if tools.get(name) is not None]
            if collisions:
                raise ValueError(f"Tools already registered: {collisions}")

        imported = Tools()
        registered = [
            _adapt_tool(
                self,
                definition,
                name=name,
                registration=registration,
            )
            for (definition, registration), name in zip(
                configured,
                names,
                strict=True,
            )
        ]
        for tool in registered:
            imported._register(tool)
        tools.merge(imported, replace=replace)
        return registered


def _adapt_tool(
    client: MCPClient,
    definition: MCPToolSpec,
    *,
    name: str,
    registration: MCPToolRegistration,
) -> Tool:
    async def invoke(arguments: _MCPArguments) -> ActionResult[object]:
        return await client.call_tool(
            definition.name,
            arguments.model_dump(mode="python"),
        )

    return Tool(
        name=name,
        description=definition.description,
        fn=invoke,
        param_model=_MCPArguments,
        parameters=definition.input_schema,
        metadata=ToolMetadata(
            effects=frozenset(registration.effects),
            tags=frozenset(registration.tags),
            extra={
                **dict(registration.metadata),
                "mcp": dict(definition.metadata),
            },
        ),
        requires_approval=registration.requires_approval,
    )
