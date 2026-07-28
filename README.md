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
    ActionResult,
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
if result.ok:
    matches = result.result
```

Set `requires_approval=True` on an action to mark its `Tool` as requiring
application-level approval before execution. The flag defaults to `False`.

`ActionResult` is generic, so applications can construct and annotate concrete
result types without falling back to `Any`:

```python
typed_result = ActionResult[list[str]].success(["first", "second"])
```

Project-specific result fields belong in a typed subclass:

```python
class ProjectActionResult[ResultT](ActionResult[ResultT]):
    trace_id: str | None = None
    citations: tuple[str, ...] = ()


tools = Tools(result_type=ProjectActionResult[object])
```

Raw tool return values are wrapped as successful results. Resolution and validation
failures become failed results, while the error boundary logs unexpected exceptions
with their traceback and returns a generic internal error. The base result rejects
unknown fields so project-specific data remains explicitly typed. Because tool
dispatch by name is dynamic and a registry can contain heterogeneous return types,
`Tools.execute()` returns `ActionResult[object]`; callers can narrow its `result` or
return a specialized `ActionResult` directly from a tool.

Plain function parameters work without a Pydantic model:

```python
@tools.action("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

Use `provided(...)` and `requires(...)` when schema exposure depends on the active
`ToolContext`. Use
`description_from_context(..., render=..., fallback=...)` for context-dependent
tool descriptions. Custom middleware subclasses `ToolMiddleware` and can inspect
or wrap each `ToolCall`.

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
