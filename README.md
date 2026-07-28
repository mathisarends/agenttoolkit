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

## Skills

Local Agent Skills are discovered from directories containing one subdirectory
per skill and a `SKILL.md` in each:

```python
from agenttoolkit import Skills, ToolContext, Tools, register_skill_tools

skills = Skills.from_local_dir("./skills")

# Put the compact catalog in the agent's system prompt.
system_prompt = f"You are helpful.\n\n{skills.catalog()}"

# Progressive loading is available directly...
instructions = skills.load("internet-research")
resource = skills.read_resource("internet-research", "references/guide.md")

# ...or through explicitly registered agent tools.
tools = Tools(context=ToolContext(skills))
register_skill_tools(tools)
```

`register_skill_tools` adds `load_skill`, `read_skill_resource`, and
`run_skill_script`. Pass `include_scripts=False` when the agent must not execute
bundled code. Resource paths are confined to the selected skill directory and
scripts run directly without a shell, but skill directories and their scripts
must still be treated as trusted code.

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
