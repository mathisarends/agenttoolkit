"""Connect to an MCP server and expose its tools through agenttoolkit.

Run with:
    uv run --extra mcp examples/mcp_client.py

The server lives in this process so the example is self-contained. For an
external server, replace ``MCPServerClient`` with ``StdioMCPClient`` or
``StreamableHTTPMCPClient``.
"""

import asyncio

from mcp.server import MCPServer

from agenttoolkit import Tools
from agenttoolkit.mcp import MCPServerClient

server = MCPServer("example")


@server.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"


async def main() -> None:
    tools = Tools()

    async with MCPServerClient(server) as client:
        registered = await client.register_tools(tools, prefix="mcp_")

        print("Registered MCP tools:")
        for tool in registered:
            print(f"- {tool.name}: {tool.description}")

        result = await tools.execute("mcp_greet", {"name": "Ada"})
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
