from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from agenttk import (
    ActionResult,
    Inject,
    Tool,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolMiddleware,
    Tools,
    build_schema,
    provided,
    requires,
)


class Service:
    def __init__(self, name: str, *, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled


class OtherService:
    pass


class StatusParams(BaseModel):
    item: str
    count: int | None = None


def test_context_prefers_latest_dependency_and_supports_lifecycle() -> None:
    first = Service("first")
    latest = Service("latest")
    other = OtherService()
    context = ToolContext(None, first).provide(other, None, latest)

    assert len(context) == 3
    assert context.resolve(Service) is latest
    assert context.resolve(OtherService) is other
    assert context.without(Service) is context
    assert context.resolve(Service) is None
    assert context.clear() is context
    assert len(context) == 0


def test_availability_predicates_can_be_composed() -> None:
    enabled = ToolContext(Service("enabled"))
    disabled = ToolContext(Service("disabled", enabled=False))
    has_service = provided(Service)
    is_enabled = requires(Service, predicate=lambda service: service.enabled)

    assert (has_service & is_enabled)(enabled)
    assert not (has_service & is_enabled)(disabled)
    assert (provided(OtherService) | is_enabled)(enabled)
    assert (~has_service)(None)
    assert not is_enabled(None)


@pytest.mark.asyncio
async def test_optional_injected_dependency_uses_function_default() -> None:
    tools = Tools()

    @tools.action("Identify the configured service")
    def identify(service: Inject[Service] = None) -> str:
        return "default" if service is None else service.name

    assert await tools.execute("identify") == ActionResult.success("default")
    assert await tools.execute(
        "identify",
        context=ToolContext(Service("injected")),
    ) == ActionResult.success("injected")


@pytest.mark.asyncio
async def test_missing_required_injection_is_returned_as_failure() -> None:
    tools = Tools()

    @tools.action("Use a required service")
    def identify(service: Inject[Service]) -> str:
        return service.name

    result = await tools.execute("identify")

    assert result == ActionResult.fail("Internal tool error.")


@pytest.mark.asyncio
async def test_unavailable_and_unknown_tools_report_available_names() -> None:
    tools = Tools()

    @tools.action("Always available")
    def public() -> None:
        pass

    @tools.action("Requires a service", available_when=provided(Service))
    def private() -> None:
        pass

    unavailable = await tools.execute("private")
    unknown = await tools.execute("missing")

    assert unavailable.error == "Unknown tool 'private'. Available: ['public']"
    assert unknown.error == "Unknown tool 'missing'. Available: ['public']"


class RecordingMiddleware(ToolMiddleware):
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __call__(
        self,
        call: ToolCall,
        next: Callable[
            [ToolCall],
            Awaitable[ActionResult[object]],
        ],
    ) -> ActionResult[object]:
        self.events.append(f"before:{getattr(call.params, 'value', None)}")
        result = await next(call)
        self.events.append(f"after:{result.result}")
        return result


class ProjectActionResult[ResultT = str](ActionResult[ResultT]):
    trace_id: str | None = None
    citations: tuple[str, ...] = ()


@pytest.mark.asyncio
async def test_custom_middleware_wraps_execution() -> None:
    events: list[str] = []
    tools = Tools(middleware=[RecordingMiddleware(events)])

    @tools.action("Double a number")
    def double(value: int) -> int:
        return value * 2

    result = await tools.execute("double", {"value": "3"})

    assert result == ActionResult[int].success(6)
    assert events[0] == "before:3"
    assert events[1] == "after:6"


@pytest.mark.asyncio
async def test_project_can_extend_and_specialize_action_result() -> None:
    tools = Tools(result_type=ProjectActionResult[object])

    @tools.action("Double a number")
    def double(value: int) -> int:
        return value * 2

    @tools.action("Fail")
    def fail() -> None:
        raise RuntimeError("secret")

    result = await tools.execute("double", {"value": 3})
    invalid = await tools.execute("double", {})
    failed = await tools.execute("fail")

    assert result == ProjectActionResult[object].success(6)
    assert isinstance(result, ProjectActionResult)
    assert result.trace_id is None
    assert isinstance(invalid, ProjectActionResult)
    assert not invalid.ok
    assert "value" in (invalid.error or "")
    assert isinstance(failed, ProjectActionResult)
    assert failed == ProjectActionResult[object].fail("Internal tool error.")

    typed = ProjectActionResult[int].success(
        6,
        trace_id="trace-123",
        citations=("doc-1",),
    )
    assert typed.result == 6
    assert typed.trace_id == "trace-123"
    assert typed.model_dump()["citations"] == ("doc-1",)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ActionResult[int].success(6, trace_id="not-a-core-field")

    with pytest.raises(ValidationError, match="int_parsing"):
        ActionResult[int].model_validate({"ok": True, "result": "not-an-integer"})


def test_unparametrized_action_result_defaults_to_str() -> None:
    assert ActionResult.success("text").result == "text"
    assert ActionResult.fail("boom").error == "boom"
    assert ProjectActionResult.success("text").result == "text"

    with pytest.raises(ValidationError, match="string_type"):
        ActionResult.success(3)


def test_registry_merge_iteration_and_replacement_are_explicit() -> None:
    first = Tools()
    second = Tools()

    @first.action("Old implementation", name="shared")
    def old() -> str:
        return "old"

    @second.action("New implementation", name="shared")
    def new() -> str:
        return "new"

    with pytest.raises(ValueError, match="already registered"):
        first.merge(second)

    first.merge(second, replace=True)

    assert len(first) == 1
    assert next(iter(first)).description == "New implementation"


def test_available_tools_always_use_registry_context() -> None:
    tools = Tools(context=ToolContext(Service("registry")))

    @tools.action("Requires a service", available_when=provided(Service))
    def current() -> None:
        pass

    assert [tool.name for tool in tools.get_available()] == ["current"]
    assert tools.get_schema(context=ToolContext()) == []
    assert [tool.name for tool in tools.get_available()] == ["current"]

    with pytest.raises(ValueError, match="not a valid ToolSchemaFormat"):
        tools.get_schema("invalid")


def test_status_supports_templates_callables_and_missing_values() -> None:
    template_tool = Tool(
        "template",
        "Template status",
        lambda params: None,
        param_model=StatusParams,
        metadata=ToolMetadata(status="Processing {item}"),
    )
    callable_tool = Tool(
        "callable",
        "Callable status",
        lambda params: None,
        param_model=StatusParams,
        metadata=ToolMetadata(status=lambda params: f"{params.item}:{params.count}"),
    )
    params = StatusParams(item="document", count=2)

    assert template_tool.format_status(params) == "Processing document"
    assert template_tool.format_status({}) == "Processing {item}"
    assert callable_tool.format_status({"item": "document", "count": 2}) == (
        "document:2"
    )


def test_status_requires_param_model_and_tool_name() -> None:
    with pytest.raises(ValueError, match="status requires a param_model"):
        Tool(
            "invalid",
            "Invalid status",
            lambda: None,
            metadata=ToolMetadata(status="Working"),
        )

    with pytest.raises(ValueError, match="cannot be empty"):
        Tool("", "Missing name", lambda: None)


def test_tools_can_declare_approval_requirement() -> None:
    tool = Tool("safe", "Safe action", lambda: None)
    tools = Tools()

    assert tool.requires_approval is False

    @tools.action("Sensitive action", requires_approval=True)
    def sensitive() -> None:
        pass

    assert tools.get("sensitive").requires_approval is True


def test_metadata_is_defensively_copied_and_immutable() -> None:
    tags = {"read"}
    extra: dict[str, Any] = {"owner": "platform"}
    metadata = ToolMetadata(tags=tags, extra=extra)
    tags.add("write")
    extra["owner"] = "changed"

    assert metadata.tags == frozenset({"read"})
    assert metadata.extra == {"owner": "platform"}
    with pytest.raises(TypeError):
        metadata.extra["owner"] = "changed"


def test_callable_schema_rejects_variadics_and_requires_input() -> None:
    def variadic(*values: str) -> None:
        pass

    with pytest.raises(TypeError, match="cannot use variadic parameters"):
        build_schema(variadic)

    with pytest.raises(ValueError, match="callable or param_model"):
        build_schema()


@pytest.mark.asyncio
async def test_param_model_binding_must_be_unambiguous() -> None:
    tools = Tools()

    @tools.action("Ambiguous", params=StatusParams)
    def ambiguous(first: object, second: object) -> None:
        pass

    result = await tools.execute("ambiguous", {"item": "document"})

    assert result == ActionResult.fail("Internal tool error.")
