from collections.abc import Mapping
from inspect import isabstract
from io import StringIO
from typing import Any, cast

import httpx2
import pytest
from mcp_types import CallToolResult, ListToolsResult, TextContent
from mcp_types import Tool as MCPTool

from agenttoolkit import Tools
from agenttoolkit.mcp import (
    MCPClient,
    MCPServerClient,
    MCPToolPage,
    MCPToolRegistration,
    MCPToolSpec,
    SSEMCPClient,
    StdioMCPClient,
    StreamableHTTPMCPClient,
)
from agenttoolkit.mcp import client as client_module
from agenttoolkit.tools import ActionResult


class RecordingMCPClient(MCPClient):
    def __init__(self, pages: Mapping[str | None, MCPToolPage]) -> None:
        self.pages = pages
        self.cursors: list[str | None] = []
        self.calls: list[tuple[str, Mapping[str, Any] | None]] = []

    async def list_tools(self, *, cursor: str | None = None) -> MCPToolPage:
        self.cursors.append(cursor)
        return self.pages[cursor]

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ActionResult[object]:
        self.calls.append((name, arguments))
        return ActionResult[object].success({"called": name})


def test_mcp_client_is_an_abstract_base_class() -> None:
    assert isabstract(MCPClient)
    assert issubclass(MCPServerClient, MCPClient)
    assert issubclass(StdioMCPClient, MCPClient)
    assert issubclass(StreamableHTTPMCPClient, MCPClient)
    assert issubclass(SSEMCPClient, MCPClient)


@pytest.mark.asyncio
async def test_abc_registers_paginated_and_configured_tools() -> None:
    weather = MCPToolSpec(
        name="weather",
        description="Get the weather",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        metadata={"source": "remote"},
    )
    ignored = MCPToolSpec(
        name="ignored",
        description="Ignored",
        input_schema={"type": "object"},
    )
    client = RecordingMCPClient(
        {
            None: MCPToolPage((weather,), next_cursor="next"),
            "next": MCPToolPage((ignored,)),
        }
    )
    tools = Tools()

    registered = await client.register_tools(
        tools,
        prefix="mcp_",
        configure=lambda definition: (
            MCPToolRegistration(
                name="forecast",
                kind="weather",
                tags=("remote",),
                metadata={"owner": "agent"},
            )
            if definition.name == "weather"
            else None
        ),
    )
    result = await tools.execute("mcp_forecast", {"city": "Berlin"})

    assert client.cursors == [None, "next"]
    assert [tool.name for tool in registered] == ["mcp_forecast"]
    assert registered[0].kind == "weather"
    assert registered[0].tags == frozenset({"remote"})
    assert registered[0].extra == {
        "owner": "agent",
        "mcp": {"source": "remote"},
    }
    assert client.calls == [("weather", {"city": "Berlin"})]
    assert result == ActionResult[object].success({"called": "weather"})


@pytest.mark.asyncio
async def test_abc_rejects_duplicate_registered_names() -> None:
    definitions = tuple(
        MCPToolSpec(
            name=name,
            description=name,
            input_schema={"type": "object"},
        )
        for name in ("first", "second")
    )
    client = RecordingMCPClient({None: MCPToolPage(definitions)})

    with pytest.raises(ValueError, match="not unique"):
        await client.register_tools(
            Tools(),
            configure=lambda _: MCPToolRegistration(name="same"),
        )


def test_stdio_client_builds_its_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = object()
    captured: dict[str, Any] = {}

    def fake_stdio_client(parameters: Any, *, errlog: Any) -> object:
        captured["parameters"] = parameters
        captured["errlog"] = errlog
        return transport

    monkeypatch.setattr(client_module, "stdio_client", fake_stdio_client)
    errlog = StringIO()

    client = StdioMCPClient(
        "python",
        ("server.py", "--quiet"),
        env={"TOKEN": "secret"},
        cwd="servers",
        encoding="utf-16",
        encoding_error_handler="replace",
        errlog=errlog,
        name="test-client",
    )

    parameters = captured["parameters"]
    assert parameters.command == "python"
    assert parameters.args == ["server.py", "--quiet"]
    assert parameters.env == {"TOKEN": "secret"}
    assert parameters.cwd == "servers"
    assert parameters.encoding == "utf-16"
    assert parameters.encoding_error_handler == "replace"
    assert captured["errlog"] is errlog
    assert client._server is transport
    assert client._client_options == {"name": "test-client"}


def test_streamable_http_client_builds_its_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = object()
    http_client = cast(httpx2.AsyncClient, object())
    captured: dict[str, Any] = {}

    def fake_streamable_http_client(
        url: str,
        *,
        http_client: Any,
        terminate_on_close: bool,
    ) -> object:
        captured.update(
            url=url,
            http_client=http_client,
            terminate_on_close=terminate_on_close,
        )
        return transport

    monkeypatch.setattr(
        client_module,
        "streamable_http_client",
        fake_streamable_http_client,
    )

    client = StreamableHTTPMCPClient(
        "https://mcp.example.test",
        http_client=http_client,
        terminate_on_close=False,
        name="test-client",
    )

    assert captured == {
        "url": "https://mcp.example.test",
        "http_client": http_client,
        "terminate_on_close": False,
    }
    assert client._server is transport
    assert client._client_options == {"name": "test-client"}


def test_sse_client_builds_its_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = object()
    auth = cast(httpx2.Auth, object())
    captured: dict[str, Any] = {}

    def fake_sse_client(
        url: str,
        *,
        headers: dict[str, Any] | None,
        timeout: float,
        sse_read_timeout: float,
        auth: Any,
    ) -> object:
        captured.update(
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
            auth=auth,
        )
        return transport

    monkeypatch.setattr(client_module, "sse_client", fake_sse_client)

    client = SSEMCPClient(
        "https://mcp.example.test/events",
        headers={"Authorization": "Bearer token"},
        timeout=1.5,
        read_timeout=42.0,
        auth=auth,
        name="test-client",
    )

    assert captured == {
        "url": "https://mcp.example.test/events",
        "headers": {"Authorization": "Bearer token"},
        "timeout": 1.5,
        "sse_read_timeout": 42.0,
        "auth": auth,
    }
    assert client._server is transport
    assert client._client_options == {"name": "test-client"}


@pytest.mark.asyncio
async def test_server_client_manages_session_and_adapts_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = object()
    events: list[object] = []

    class FakeSDKClient:
        def __init__(self, server: object, **options: Any) -> None:
            events.append(("init", server, options))

        async def __aenter__(self) -> "FakeSDKClient":
            events.append("enter")
            return self

        async def __aexit__(self, *exception: object) -> None:
            events.append(("exit", *exception))

        async def list_tools(self, *, cursor: str | None) -> ListToolsResult:
            events.append(("list_tools", cursor))
            return ListToolsResult(
                tools=[
                    MCPTool(
                        name="weather",
                        title="Weather",
                        input_schema={"type": "object"},
                    )
                ],
                next_cursor="next",
            )

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any] | None,
        ) -> CallToolResult:
            events.append(("call_tool", name, arguments))
            return CallToolResult(content=[TextContent(text="sunny")])

    monkeypatch.setattr(client_module, "Client", FakeSDKClient)
    client = MCPServerClient(cast(Any, source), name="test-client")

    with pytest.raises(
        RuntimeError,
        match="must be used within an async context manager",
    ):
        await client.list_tools()

    async with client as connected:
        assert connected is client
        page = await client.list_tools(cursor="cursor")
        result = await client.call_tool("weather", {"city": "Berlin"})
        with pytest.raises(RuntimeError, match="already connected"):
            await client.__aenter__()

    assert page.next_cursor == "next"
    assert page.tools[0].name == "weather"
    assert page.tools[0].description == "Weather"
    assert page.tools[0].input_schema == {"type": "object"}
    assert result == ActionResult[object].success("sunny")
    assert events == [
        ("init", source, {"name": "test-client"}),
        "enter",
        ("list_tools", "cursor"),
        ("call_tool", "weather", {"city": "Berlin"}),
        ("exit", None, None, None),
    ]
