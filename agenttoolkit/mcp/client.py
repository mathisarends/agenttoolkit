from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Self, TextIO

try:
    import httpx2
    from mcp import Client
    from mcp.client import Transport
    from mcp.client.sse import sse_client
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server import MCPServer, Server
    from mcp_types import CallToolResult, TextContent
except ModuleNotFoundError as exc:
    if exc.name and exc.name.split(".", maxsplit=1)[0] in {
        "httpx2",
        "mcp",
        "mcp_types",
    }:
        raise ModuleNotFoundError(
            "MCP support requires the optional dependencies from the 'mcp' extra. "
            "Install them with `pip install 'agenttoolkit[mcp]'`."
        ) from exc
    raise

from agenttoolkit.mcp.base import MCPClient, MCPToolPage, MCPToolSpec
from agenttoolkit.tools.results import ActionResult

type MCPServerSource = Server | MCPServer | Transport | str


class _MCPClient(MCPClient):
    def __init__(
        self,
        server: MCPServerSource,
        **client_options: Any,
    ) -> None:
        self._server = server
        self._client_options = client_options
        self._client: Client | None = None

    async def __aenter__(self) -> Self:
        if self._client is not None:
            raise RuntimeError("MCP client is already connected")
        client = Client(self._server, **self._client_options)
        self._client = await client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.__aexit__(exc_type, exc_value, traceback)

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError(
                "MCP client must be used within an async context manager"
            )
        return self._client

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
    ) -> MCPToolPage:
        page = await self.client.list_tools(cursor=cursor)
        return MCPToolPage(
            tools=tuple(
                MCPToolSpec(
                    name=definition.name,
                    description=(
                        definition.description or definition.title or definition.name
                    ),
                    input_schema=definition.input_schema,
                    metadata=definition.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_none=True,
                    ),
                )
                for definition in page.tools
            ),
            next_cursor=page.next_cursor,
        )

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ActionResult[object]:
        result = await self.client.call_tool(
            name,
            None if arguments is None else dict(arguments),
        )
        payload = _result_payload(result)
        if result.is_error:
            return ActionResult[object].fail(_error_message(name, payload))
        return ActionResult[object].success(payload)


class MCPServerClient(_MCPClient):
    """MCP client for an existing MCP server or transport source."""


class StdioMCPClient(_MCPClient):
    def __init__(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
        encoding: str = "utf-8",
        encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
        errlog: TextIO = sys.stderr,
        **client_options: Any,
    ) -> None:
        parameters = StdioServerParameters(
            command=command,
            args=list(args),
            env=None if env is None else dict(env),
            cwd=cwd,
            encoding=encoding,
            encoding_error_handler=encoding_error_handler,
        )
        super().__init__(
            stdio_client(parameters, errlog=errlog),
            **client_options,
        )


class StreamableHTTPMCPClient(_MCPClient):
    def __init__(
        self,
        url: str,
        *,
        http_client: httpx2.AsyncClient | None = None,
        terminate_on_close: bool = True,
        **client_options: Any,
    ) -> None:
        transport = streamable_http_client(
            url,
            http_client=http_client,
            terminate_on_close=terminate_on_close,
        )
        super().__init__(transport, **client_options)


class SSEMCPClient(_MCPClient):
    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, Any] | None = None,
        timeout: float = 5.0,
        read_timeout: float = 300.0,
        auth: httpx2.Auth | None = None,
        **client_options: Any,
    ) -> None:
        transport = sse_client(
            url,
            headers=None if headers is None else dict(headers),
            timeout=timeout,
            sse_read_timeout=read_timeout,
            auth=auth,
        )
        super().__init__(transport, **client_options)


def _result_payload(result: CallToolResult) -> object:
    if result.structured_content is not None:
        return result.structured_content

    text = [block.text for block in result.content if isinstance(block, TextContent)]
    if len(text) == len(result.content):
        return "\n".join(text)
    return [
        block.model_dump(mode="json", by_alias=True, exclude_none=True)
        for block in result.content
    ]


def _error_message(name: str, payload: object) -> str:
    if isinstance(payload, str) and payload:
        return payload
    if payload:
        return json.dumps(payload, ensure_ascii=False)
    return f"MCP tool '{name}' failed"
