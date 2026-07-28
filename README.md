# agenttoolkit

`agenttoolkit` provides one provider-neutral definition for tools exposed to
LLM agents. Define a tool once — schema, availability, metadata, and
execution logic — and expose it to OpenAI, Anthropic, or any other provider
without duplicating definitions.

It intentionally contains no application-specific tools and no agent loop:
it is a building block, not a framework.

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Defining tools](#defining-tools)
  - [Plain function parameters](#plain-function-parameters)
  - [Pydantic parameter models](#pydantic-parameter-models)
  - [Registering `Tool` objects directly](#registering-tool-objects-directly)
- [Dependency injection with `ToolContext`](#dependency-injection-with-toolcontext)
- [Conditional availability and descriptions](#conditional-availability-and-descriptions)
- [Schema generation](#schema-generation)
- [Executing tool calls](#executing-tool-calls)
- [Results (`ActionResult`)](#results-actionresult)
  - [Typed and project-specific results](#typed-and-project-specific-results)
- [Middleware](#middleware)
  - [Built-in middleware chain](#built-in-middleware-chain)
  - [Writing custom middleware](#writing-custom-middleware)
- [Tool metadata](#tool-metadata)
- [Approval-gated tools](#approval-gated-tools)
- [Merging registries](#merging-registries)
- [Skills](#skills)
  - [Skill directory layout](#skill-directory-layout)
  - [Discovering and using skills](#discovering-and-using-skills)
  - [Running skill scripts](#running-skill-scripts)
- [Development](#development)

## Features

- Registration through a `@tools.action` decorator or explicit `Tool`
  objects.
- JSON Schema generation from plain Python function signatures or Pydantic
  models — no need to hand-write schemas.
- Runtime metadata such as action kind, human-readable status text, tags,
  and arbitrary custom values, kept separate from the model-facing schema.
- Context-based dependency injection (`Inject[T]`) so tools can receive
  application services without the model ever seeing them.
- Conditional tool availability and dynamic, context-aware descriptions.
- Sync and async tool execution behind a single async API.
- A composable middleware pipeline (error boundary, resolution, validation,
  logging) that applications can extend or replace.
- Thin, dependency-free schema adapters for OpenAI and Anthropic tool-call
  formats.
- Generic `ActionResult` type so applications can add project-specific
  result fields without falling back to `Any`.
- Local Agent Skills discovery and progressive loading, compatible with the
  `SKILL.md` convention.

## Installation

```console
uv add agenttoolkit
```

Requires Python 3.12–3.14. Modules that use forward references should add
`from __future__ import annotations`, since lazy annotation evaluation
(PEP 649) is native only to 3.14+.

## Quickstart

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


anthropic_schemas = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

result = await tools.execute("search", {"query": "tool middleware"})
if result.ok:
    matches = result.result
```

## Defining tools

### Plain function parameters

Tools without a Pydantic model derive their schema from the function
signature. Type hints become JSON Schema types; `Annotated[..., "text"]`
supplies a field description.

```python
@tools.action("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

### Pydantic parameter models

Pass `params=` to validate arguments against an explicit model. The model
is matched to the function parameter whose annotation equals `params`, or —
if there's exactly one non-injected parameter — passed positionally by
keyword.

```python
class AddParams(BaseModel):
    a: int
    b: int = Field(description="Second addend")


@tools.action("Add two integers.", params=AddParams)
def add(params: AddParams) -> int:
    return params.a + params.b
```

### Registering `Tool` objects directly

`@tools.action` is sugar over constructing a `Tool` and calling
`tools.register(...)`. Build one directly when you need to construct tools
programmatically:

```python
from agenttoolkit import Tool, ToolMetadata

tool = Tool(
    name="add",
    description="Add two integers.",
    fn=add,
    param_model=AddParams,
    metadata=ToolMetadata(kind="compute"),
)
tools.register(tool)              # raises if "add" is already registered
tools.register(tool, replace=True)  # overwrite an existing registration
```

## Dependency injection with `ToolContext`

`ToolContext` carries application services that tools need but that should
never appear in the model-facing schema. Wrap a parameter in `Inject[T]` and
it is resolved from context at call time instead of being part of the
argument schema:

```python
context = ToolContext(SearchClient(), some_other_service)
tools.set_context(context)
```

`ToolContext.resolve(T)` returns the most recently provided instance of type
`T` (or a subclass), searching in reverse insertion order. Useful mutators:

```python
context.provide(extra_service)     # append more dependencies
context.without(SearchClient)      # drop instances of a type
context.clear()                    # remove everything
```

If an `Inject[T]` parameter has no default and no matching dependency is
found in context, execution raises `ValueError` rather than silently
passing `None`.

## Conditional availability and descriptions

Use `provided(...)` and `requires(...)` to expose a tool only when its
dependency is present (and, optionally, satisfies a predicate):

```python
from agenttoolkit import provided, requires

@tools.action(
    "Look up account balance.",
    available_when=provided(BankingClient),
)
def balance() -> float: ...

@tools.action(
    "Issue a refund.",
    available_when=requires(BankingClient, predicate=lambda c: c.is_admin),
)
def refund(amount: float) -> None: ...
```

`ToolAvailability` predicates compose with `&`, `|`, and `~`:

```python
available_when=provided(BankingClient) & ~requires(BankingClient, predicate=lambda c: c.read_only)
```

Use `description_from_context(...)` when a tool's description itself should
depend on context (e.g. embedding a resolved account name):

```python
from agenttoolkit import description_from_context

description = description_from_context(
    BankingClient,
    render=lambda client: f"Look up the balance for {client.account_name}.",
    fallback="Look up account balance.",
)

@tools.action(description)
def balance() -> float: ...
```

## Schema generation

`Tools.get_schema(...)` returns the schema for every tool available in the
active (or given) context, in native, OpenAI, or Anthropic form:

```python
native_schemas = tools.get_schema()
openai_schemas = tools.get_schema(ToolSchemaFormat.OPENAI)
anthropic_schemas = tools.get_schema(ToolSchemaFormat.ANTHROPIC)
```

`Tools.available(context=...)` returns the underlying `Tool` objects instead
of schemas, e.g. for building a custom catalog.

The standalone `build_schema(func, param_model=...)` helper produces the raw
JSON Schema for a callable or model without constructing a `Tool`.

## Executing tool calls

```python
result = await tools.execute("search", {"query": "tool middleware"}, context=context)
```

`execute` runs the call through the middleware chain: tool resolution,
argument validation against the tool's parameter model, dependency
injection, invocation (sync or async), and error handling. It always
returns an `ActionResult`, never raises for expected failures (unknown
tool name, invalid arguments, exceptions inside the tool).

## Results (`ActionResult`)

```python
class ActionResult[ResultT](BaseModel):
    ok: bool
    result: ResultT | None = None
    error: str | None = None
```

Raw tool return values are wrapped as successful results automatically. A
tool may instead return an `ActionResult` directly (e.g. to set `error`
with `ok=True`, or to populate custom subclass fields) — `Tools.execute`
passes such a return value through unchanged.

```python
typed_result = ActionResult[list[str]].success(["first", "second"])
failed_result = ActionResult[list[str]].fail("no matches")
```

Because tool dispatch by name is dynamic and a registry can contain
heterogeneous return types, `Tools.execute()` returns `ActionResult[object]`;
narrow `result` at the call site or return a specialized `ActionResult`
directly from the tool.

### Typed and project-specific results

`ActionResult` rejects unknown fields, so project-specific data belongs in a
typed subclass, wired up via `Tools(result_type=...)`:

```python
class ProjectActionResult[ResultT](ActionResult[ResultT]):
    trace_id: str | None = None
    citations: tuple[str, ...] = ()


tools = Tools(result_type=ProjectActionResult[object])
```

Every result produced by the built-in middleware chain (validation
failures, unknown-tool errors, the generic internal error on unexpected
exceptions) is constructed via this configured `result_type`.

## Middleware

### Built-in middleware chain

By default, every call passes through:

1. `ErrorBoundaryMiddleware` — catches unexpected exceptions, logs them with
   their traceback, and returns a generic internal error result instead of
   propagating.
2. `ToolResolutionMiddleware` — resolves the tool by name and checks
   `available_when`; unknown or unavailable tools fail with the list of
   currently available tool names.
3. `ParamValidationMiddleware` — validates raw arguments against the tool's
   input model, turning a `ValidationError` into a failed `ActionResult`.
4. `CallLoggingMiddleware` — logs each call's arguments and outcome
   (name, ok/fail, elapsed time), unless custom middleware is supplied.

### Writing custom middleware

Pass `middleware=` to `Tools(...)` to run additional middleware *before*
the built-in core (error boundary → resolution → validation). Subclass
`ToolMiddleware` and inspect or wrap the `ToolCall`:

```python
from agenttoolkit import ToolCall, ToolMiddleware


class TimeoutMiddleware(ToolMiddleware):
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    async def __call__(self, call: ToolCall, next):
        return await asyncio.wait_for(next(call), timeout=self._seconds)


tools = Tools(middleware=[TimeoutMiddleware(5.0)])
```

Supplying `middleware=` replaces the default `CallLoggingMiddleware` step;
add your own logging middleware to the list if you still want it.

## Tool metadata

`ToolMetadata` carries runtime hints that do not belong in the model-facing
schema:

- `kind` — a free-form category (e.g. `"read"`, `"write"`, `"compute"`).
- `status` — a human-readable status message, either a `str.format`
  template referencing parameter names (`"Searching for {query}..."`) or a
  `Callable[[BaseModel], str]` for more complex formatting. Validated at
  registration time against the tool's parameter model.
- `tags` — a `frozenset[str]` for grouping or filtering tools.
- `extra` — an arbitrary read-only mapping for application-specific values.

```python
tool.metadata.kind
tool.metadata.tags
tool.format_status(params)  # renders the status template/callable
```

## Approval-gated tools

Set `requires_approval=True` on `@tools.action` (or `Tool(...)`) to mark a
tool as requiring application-level approval before execution. The flag
defaults to `False` and is purely informational — `agenttoolkit` does not
enforce approval itself; check `tool.requires_approval` in your own
call-handling code before invoking `Tools.execute`.

## Merging registries

Combine tools from multiple `Tools` instances — e.g. when composing a
registry from several feature modules:

```python
tools.merge(other_tools)                 # raises on name collisions
tools.merge(other_tools, replace=True)   # other_tools wins on collisions
```

## Skills

Local Agent Skills are discovered from directories containing one
subdirectory per skill, each with a `SKILL.md` file using YAML frontmatter
(`name`, `description`, and optional `license`, `compatibility`, `metadata`,
`allowed-tools`) followed by Markdown instructions.

### Skill directory layout

```
skills/
  internet-research/
    SKILL.md
    references/
      guide.md
    scripts/
      search.py
```

`name` must be 1–64 lowercase letters, numbers, or hyphens, and must match
its parent directory name.

### Discovering and using skills

```python
from agenttoolkit import Skills

skills = Skills.from_local_dir("./skills")

# Put the compact catalog in the agent's system prompt.
system_prompt = f"You are helpful.\n\n{skills.catalog()}"

# Progressive loading: full instructions + file listing for one skill...
instructions = skills.load("internet-research")

# ...then read a specific resource on demand.
resource = skills.read_resource("internet-research", "references/guide.md")
```

`Skills.from_local_dir` accepts multiple directories; a skill discovered
later overrides one with the same name from an earlier directory (logged as
a warning). `SKILL.md` is re-parsed from disk on each `load`/`get`, so
instructions can be edited without restarting the process.

Resource paths are confined to the selected skill's directory — absolute
paths and traversal outside the skill directory are rejected. Skill
directories and their scripts must still be treated as trusted code.

### Running skill scripts

```python
output = await skills.run_script("internet-research", "scripts/search.py", args=["python packaging"])
```

Scripts run directly via their interpreter (no shell), with a configurable
timeout (default 60s, `run_script(..., timeout=...)`). `.py` scripts run
under the current Python interpreter; `.sh`/`.bash` scripts require `bash`
on `PATH`. Output is the process's stdout on success, or an `Error: ...` /
`Error (exit code N): ...` string on failure or timeout — this call never
raises for script failures.

## Development

Install the locked development environment and run all quality checks:

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

The test command measures branch coverage for `agenttoolkit` and fails
below 90%. Dependabot groups Python dependency updates into one weekly pull
request; the same CI matrix validates every update on Python 3.12, 3.13,
and 3.14.
