from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from .binding import ToolAvailability, ToolDescription
from .context import ToolContext
from .schema import ToolSchema, _schema_model


class ActionKind(StrEnum):
    GENERIC = "generic"
    READ = "read"
    MUTATE = "mutate"
    DESTRUCTIVE = "destructive"
    END_SESSION = "end_session"


class ToolSchemaFormat(StrEnum):
    NATIVE = "native"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


type StatusFormatter = str | Callable[[BaseModel], str]


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    """Runtime hints which do not belong in an LLM function schema."""

    kind: ActionKind | str = ActionKind.GENERIC
    respond: bool = True
    result_instruction: str | None = None
    status: StatusFormatter | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", frozenset(self.tags))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


class Tool:
    """A callable together with its schema, context rules, and runtime metadata."""

    def __init__(
        self,
        name: str,
        description: str | ToolDescription,
        fn: Callable,
        *,
        param_model: type[BaseModel] | None = None,
        metadata: ToolMetadata | None = None,
        available_when: ToolAvailability | None = None,
    ) -> None:
        if not name:
            raise ValueError("Tool name cannot be empty")
        self.name = name
        self.description = description
        self.fn = fn
        self.param_model = param_model
        self.metadata = metadata or ToolMetadata()
        self.available_when = available_when
        self.input_model = _schema_model(fn, param_model=param_model)
        self.parameters = self.input_model.model_json_schema(mode="validation")
        self._validate_status()

    @property
    def kind(self) -> ActionKind | str:
        return self.metadata.kind

    @property
    def respond(self) -> bool:
        return self.metadata.respond

    @property
    def result_instruction(self) -> str | None:
        return self.metadata.result_instruction

    @property
    def status(self) -> StatusFormatter | None:
        return self.metadata.status

    def is_available(self, context: ToolContext | None = None) -> bool:
        return True if self.available_when is None else self.available_when(context)

    def resolve_description(self, context: ToolContext | None = None) -> str:
        if isinstance(self.description, ToolDescription):
            return self.description.resolve(context)
        return self.description

    def to_schema(self, context: ToolContext | None = None) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.resolve_description(context),
            parameters=self.parameters,
        )

    def to_openai_schema(
        self,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        return self.to_schema(context).to_openai_schema()

    def to_anthropic_schema(
        self,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        return self.to_schema(context).to_anthropic_schema()

    def parse_arguments(self, arguments: str) -> dict[str, Any]:
        raw_arguments = json.loads(arguments)
        params = self.input_model.model_validate(raw_arguments)
        return params.model_dump(mode="python")

    async def execute(self, arguments: dict[str, Any]) -> Any:
        result = self.fn(**arguments)
        return await result if inspect.isawaitable(result) else result

    def format_status(self, args: BaseModel | Mapping[str, Any]) -> str | None:
        if self.status is None:
            return None
        if callable(self.status):
            model = (
                args
                if isinstance(args, BaseModel)
                else self.input_model.model_validate(dict(args))
            )
            return self.status(model)

        values = (
            args.model_dump(exclude_none=True)
            if isinstance(args, BaseModel)
            else dict(args)
        )
        try:
            return self.status.format(**values)
        except KeyError:
            return self.status

    def _validate_status(self) -> None:
        status = self.status
        if status is None:
            return
        if self.param_model is None:
            raise ValueError(f"Tool '{self.name}': status requires a param_model")
        if callable(status):
            return

        placeholders = set(re.findall(r"\{(\w+)\}", status))
        unknown = placeholders - set(self.param_model.model_fields)
        if unknown:
            raise ValueError(
                f"Tool '{self.name}': status contains unknown placeholders: {unknown}"
            )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tool) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
