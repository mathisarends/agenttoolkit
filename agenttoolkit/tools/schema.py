from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model

from .context import _INJECT_MARKER


class ToolSchema(BaseModel):
    """Canonical function-tool schema with lightweight provider adapters."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": self.model_dump(mode="json"),
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


def build_schema(
    func: Callable | None = None,
    *,
    param_model: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """Build JSON Schema from a callable or an explicit Pydantic model."""
    return _schema_model(func, param_model=param_model).model_json_schema(
        mode="validation"
    )


def _schema_model(
    func: Callable | None,
    *,
    param_model: type[BaseModel] | None,
) -> type[BaseModel]:
    if param_model is not None:
        return param_model
    if func is None:
        raise ValueError("A callable or param_model is required")
    return _model_from_callable(func)


def _model_from_callable(func: Callable) -> type[BaseModel]:
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    fields: dict[str, tuple[Any, Any]] = {}
    descriptions: dict[str, str] = {}

    for name, parameter in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        annotation = hints.get(name, str)
        if _is_injected(annotation):
            continue
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise TypeError(f"Tool '{func.__name__}' cannot use variadic parameters")

        default = (
            ... if parameter.default is inspect.Parameter.empty else parameter.default
        )
        fields[name] = (annotation, default)
        description = _annotated_description(annotation)
        if description is not None:
            descriptions[name] = description

    model = create_model(
        f"{func.__name__.title().replace('_', '')}Params",
        __config__=ConfigDict(extra="forbid", arbitrary_types_allowed=True),
        **fields,
    )
    for name, description in descriptions.items():
        model.model_fields[name].description = description
    model.model_rebuild(force=True)
    return model


def _is_injected(annotation: Any) -> bool:
    return get_origin(annotation) is Annotated and _INJECT_MARKER in get_args(
        annotation
    )


def _annotated_description(annotation: Any) -> str | None:
    if get_origin(annotation) is not Annotated:
        return None
    return next(
        (
            metadata
            for metadata in get_args(annotation)[1:]
            if isinstance(metadata, str)
        ),
        None,
    )
