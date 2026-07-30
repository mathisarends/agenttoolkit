from typing import TYPE_CHECKING, Any

from .base import (
    MCPClient,
    MCPToolConfigurator,
    MCPToolPage,
    MCPToolRegistration,
    MCPToolSpec,
)

if TYPE_CHECKING:
    from .client import (
        MCPServerClient,
        SSEMCPClient,
        StdioMCPClient,
        StreamableHTTPMCPClient,
    )

_CLIENT_EXPORTS = frozenset(
    {
        "MCPServerClient",
        "SSEMCPClient",
        "StdioMCPClient",
        "StreamableHTTPMCPClient",
    }
)

__all__ = [
    "MCPClient",
    "MCPServerClient",
    "MCPToolConfigurator",
    "MCPToolPage",
    "MCPToolRegistration",
    "MCPToolSpec",
    "SSEMCPClient",
    "StdioMCPClient",
    "StreamableHTTPMCPClient",
]


def __getattr__(name: str) -> Any:
    if name not in _CLIENT_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import client

    value = getattr(client, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
