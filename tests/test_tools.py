from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from agenttoolkit import (
    ActionKind,
    ActionResult,
    Inject,
    ToolContext,
    ToolExecutionError,
    ToolRegistry,
    ToolSchemaFormat,
    described,
    provided,
)


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)


class SearchClient:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix


@pytest.mark.asyncio
async def test_register_validate_inject_and_execute() -> None:
    client = SearchClient("found:")
    tools = ToolRegistry(context=ToolContext(client))

    @tools.action(
        "Search",
        params=SearchParams,
        kind=ActionKind.READ,
        tags=["network"],
        metadata={"owner": "knowledge"},
    )
    async def search(
        params: SearchParams,
        dependency: Inject[SearchClient],
    ) -> ActionResult:
        return ActionResult.success(f"{dependency.prefix}{params.query}:{params.limit}")

    result = await tools.execute("search", {"query": "docs"})
    tool = tools.get("search")

    assert result == ActionResult.success("found:docs:10")
    assert tool is not None
    assert tool.kind is ActionKind.READ
    assert tool.metadata.tags == frozenset({"network"})
    assert tool.metadata.extra["owner"] == "knowledge"


@pytest.mark.asyncio
async def test_plain_signature_is_validated_and_sync_result_is_wrapped() -> None:
    tools = ToolRegistry()

    @tools.action("Add numbers")
    def add(a: int, b: int = 1) -> int:
        return a + b

    assert await tools.execute("add", {"a": "2"}) == ActionResult.success(3)

    invalid = await tools.execute("add", {})
    assert not invalid.ok
    assert "a" in (invalid.error or "")


def test_schema_is_provider_neutral_with_adapters() -> None:
    tools = ToolRegistry()

    @tools.action("Search", params=SearchParams)
    def search(params: SearchParams) -> None:
        pass

    native = tools.get_schema()[0]
    openai = tools.get_schema(ToolSchemaFormat.OPENAI)[0]
    anthropic = tools.get_schema(ToolSchemaFormat.ANTHROPIC)[0]

    assert native.parameters["properties"]["query"]["description"] == "Search query"
    assert openai["type"] == "function"
    assert openai["function"]["name"] == "search"
    assert anthropic["input_schema"] == native.parameters
    assert tools.get("search").to_openai_schema() == openai
    assert tools.get("search").parse_arguments('{"query": "docs"}') == {
        "query": "docs",
        "limit": 10,
    }


def test_annotated_description_is_included_in_callable_schema() -> None:
    tools = ToolRegistry()

    @tools.action("Greet")
    def greet(name: Annotated[str, "Person to greet"]) -> None:
        pass

    parameters = tools.get_schema()[0].parameters
    assert parameters["properties"]["name"]["description"] == "Person to greet"


def test_context_controls_availability_and_description() -> None:
    tools = ToolRegistry()

    @tools.action(
        described(
            SearchClient,
            render=lambda client: f"Search with prefix {client.prefix}",
            default="Search",
        ),
        available_when=provided(SearchClient),
    )
    def search(query: str) -> None:
        pass

    assert tools.get_schema() == []

    tools.set_context(ToolContext(SearchClient("kb:")))
    schemas = tools.get_schema()
    assert schemas[0].description == "Search with prefix kb:"


@pytest.mark.asyncio
async def test_expected_and_unexpected_errors_are_separated() -> None:
    tools = ToolRegistry()

    @tools.action("Fail safely")
    def safe_failure() -> None:
        raise ToolExecutionError("Try a different query")

    @tools.action("Fail internally")
    def internal_failure() -> None:
        raise RuntimeError("secret")

    safe = await tools.execute("safe_failure")
    internal = await tools.execute("internal_failure")

    assert safe.error == "Try a different query"
    assert internal.error == "Internal tool error."


def test_duplicate_registration_and_status_validation() -> None:
    tools = ToolRegistry()

    @tools.action("First")
    def duplicate() -> None:
        pass

    with pytest.raises(ValueError, match="already registered"):

        @tools.action("Second")
        def duplicate() -> None:
            pass

    with pytest.raises(ValueError, match="unknown placeholders"):

        @tools.action(
            "Search",
            params=SearchParams,
            status="Searching {missing}",
        )
        def bad_status(params: SearchParams) -> None:
            pass
