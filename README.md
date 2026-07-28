# agenttoolkit

`agenttoolkit` provides one provider-neutral definition for tools exposed to
LLM agents. It combines:

- registration through a decorator or explicit `Tool` objects;
- JSON Schema generation from Python signatures or Pydantic models;
- runtime metadata such as action kind, status text, tags, and custom values;
- context-based dependency injection and conditional tool availability;
- sync and async execution with validation and middleware;
- thin schema adapters for OpenAI and Anthropic.

It intentionally contains no application-specific tools or agent loop.

## Example

```python
from pydantic import BaseModel, Field

from agenttoolkit import (
    Inject,
    ToolContext,
    Tools,
    ToolSchemaFormat,
)


class SearchParams(BaseModel):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, ge=1, le=20)


class SearchClient:
    async def search(self, query: str, limit: int) -> list[str]:
        return [query] * limit


tools = Tools(context=ToolContext(SearchClient()))


@tools.action(
    "Search the connected knowledge base.",
    params=SearchParams,
    kind="read",
    status="Searching for {query}...",
    tags=["search"],
    metadata={"requires_network": True},
)
async def search(
    params: SearchParams,
    client: Inject[SearchClient],
) -> list[str]:
    matches = await client.search(params.query, params.limit)
    return matches
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

Set `requires_approval=True` on an action to mark its `Tool` as requiring
application-level approval before execution. The flag defaults to `False`.

Tool results are returned unchanged. Validation and execution exceptions propagate
to the caller, so applications can choose their own result and error conventions.
Custom middleware can add an application-specific result envelope when needed.

Plain function parameters work without a Pydantic model:

```python
@tools.action("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

Use `provided(...)`, `requires(...)`, and `described(...)` when schema exposure
or descriptions depend on the active `ToolContext`. Custom middleware subclasses
`ToolMiddleware` and can inspect or wrap each `ToolCall`.

## Skills

Local Agent Skills are discovered from directories containing one subdirectory
per skill and a `SKILL.md` in each:

```python
from agenttoolkit import Skills

skills = Skills.from_local_dir("./skills")

# Put the compact catalog in the agent's system prompt.
system_prompt = f"You are helpful.\n\n{skills.catalog()}"

# Progressive loading is available directly...
instructions = skills.load("internet-research")
resource = skills.read_resource("internet-research", "references/guide.md")
```

Resource paths are confined to the selected skill directory and scripts run
directly without a shell, but skill directories and their scripts must still be
treated as trusted code.

## Development

Install the locked development environment and run all quality checks:

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

The test command measures branch coverage for `agenttoolkit` and fails below
90%. Dependabot groups Python dependency updates into one weekly pull request;
the same CI matrix validates every update on Python 3.12, 3.13, and 3.14.
