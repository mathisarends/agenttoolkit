# agenttoolkit

`agenttoolkit` provides one provider-neutral definition for tools exposed to
LLM agents. It combines:

- registration through a decorator or explicit `Tool` objects;
- JSON Schema generation from Python signatures or Pydantic models;
- runtime metadata such as action kind, status text, tags, and response hints;
- context-based dependency injection and conditional tool availability;
- sync and async execution with validation and middleware;
- thin schema adapters for OpenAI and Anthropic.

It intentionally contains no application-specific tools or agent loop.

## Example

```python
from pydantic import BaseModel, Field

from agenttoolkit import (
    ActionKind,
    ActionResult,
    Inject,
    ToolContext,
    ToolRegistry,
    ToolSchemaFormat,
)


class SearchParams(BaseModel):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, ge=1, le=20)


class SearchClient:
    async def search(self, query: str, limit: int) -> list[str]:
        return [query] * limit


tools = ToolRegistry(context=ToolContext(SearchClient()))


@tools.action(
    "Search the connected knowledge base.",
    params=SearchParams,
    kind=ActionKind.READ,
    status="Searching for {query}...",
    tags=["search"],
    metadata={"requires_network": True},
)
async def search(
    params: SearchParams,
    client: Inject[SearchClient],
) -> ActionResult:
    matches = await client.search(params.query, params.limit)
    return ActionResult.success(matches)
```

Expose only the model-facing schema:

```python
native_schemas = tools.get_schema()
openai_schemas = tools.get_schema(ToolSchemaFormat.OPENAI)
anthropic_schemas = tools.get_schema(ToolSchemaFormat.ANTHROPIC)
```

Execute a model-produced call:

```python
result = await tools.execute("search", {"query": "tool middleware"})
```

Plain function parameters work without a Pydantic model:

```python
@tools.action("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

Use `provided(...)`, `requires(...)`, and `described(...)` when schema exposure
or descriptions depend on the active `ToolContext`. Custom middleware subclasses
`ToolMiddleware` and can inspect or wrap each `ToolCall`.
