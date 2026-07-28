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
- [Dependency injection with `ToolContext`](#dependency-injection-with-toolcontext)
- [Conditional availability and descriptions](#conditional-availability-and-descriptions)
- [Driving an agent loop](#driving-an-agent-loop)
- [Results (`ActionResult`)](#results-actionresult)
- [Middleware](#middleware)
- [Merging registries](#merging-registries)
- [Filesystem and shell primitives](#filesystem-and-shell-primitives)
- [Skills](#skills)
- [Development](#development)
- [License](#license)

## Features

- Registration through a `@tools.action` decorator — no hand-written JSON
  Schema, for either plain function signatures or Pydantic models.
- Runtime metadata (`kind`, `status`, `tags`, custom fields) and an
  `requires_approval` flag, kept out of the model-facing schema but readable
  by the host loop that dispatches calls.
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
- Async filesystem and shell ports with local, Docker, and Bubblewrap
  implementations for common agent capabilities.
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

This is the shape of code you actually write and run — define tools with
the decorator, hand their schema to the model, execute whichever call it
makes, and feed the result back:

```python
from pydantic import BaseModel, Field

from agenttoolkit import ActionResult, Inject, ToolContext, Tools, ToolSchemaFormat


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
    status="Searching for {query}...",
)
async def search(params: SearchParams, client: Inject[SearchClient]) -> list[str]:
    return await client.search(params.query, params.limit)


# 1. Send the schema to the model.
schema = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

# 2. The model asks to call "search" with {"query": "tool middleware"}.
result: ActionResult[object] = await tools.execute(
    "search", {"query": "tool middleware"}
)

# 3. Feed the outcome back to the model.
if result.ok:
    matches = result.result
else:
    error_message = result.error
```

`tools.execute(...)` never raises for expected failures — an unknown tool
name, invalid arguments, or an exception inside the tool all come back as a
failed `ActionResult`, ready to hand to the model as-is.

## Defining tools

The `@tools.action(...)` decorator is the entire surface most code touches.
Parameters come from a plain function signature or, for validation and
richer schemas, a Pydantic model passed as `params=`:

```python
@tools.action("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


class RefundParams(BaseModel):
    order_id: str
    amount: float = Field(gt=0, description="Amount to refund, in USD")


@tools.action(
    "Issue a refund for an order.",
    params=RefundParams,
    kind="write",
    status="Refunding {amount} for order {order_id}...",
    tags=["billing", "write"],
    requires_approval=True,
    metadata={"owner": "billing-team"},
)
def refund(params: RefundParams, client: Inject[BillingClient]) -> str:
    client.refund(params.order_id, params.amount)
    return "refunded"
```

None of `kind`, `status`, `tags`, `requires_approval`, or `metadata` are
visible to the model — they never appear in the generated JSON Schema. They
exist for the host loop that dispatches the call:

- `kind` — a free-form category (e.g. `"read"`, `"write"`), readable as
  `tool.kind`.
- `status` — a human-readable status message, either a `str.format`
  template referencing parameter names or a `Callable[[BaseModel], str]`
  for more complex formatting. Render it with `tool.format_status(args)`
  (e.g. to show "Refunding 20.0 for order o-123..." while the call runs).
- `tags` — a `frozenset[str]` for grouping or filtering tools, readable as
  `tool.tags`.
- `metadata` — an arbitrary read-only mapping for anything else the host
  application needs, readable as `tool.extra`.
- `requires_approval` — readable as `tool.requires_approval`; check it
  before calling `tools.execute(...)` if the action needs user
  confirmation first. `agenttoolkit` does not enforce approval itself.

```python
tool = tools.get("refund")
tool.kind               # "write"
tool.tags                # frozenset({"billing", "write"})
tool.extra["owner"]      # "billing-team"
tool.requires_approval   # True
tool.format_status({"order_id": "o-123", "amount": 20.0})
# "Refunding 20.0 for order o-123..."
```

`status` is validated against `params` at registration time, so a typo in
a placeholder name (`"{amout}"`) fails fast instead of at call time.

Constructing a `Tool` directly (`from agenttoolkit import Tool, ToolMetadata`)
and calling `tools.register(tool)` is available for building tools
programmatically, but is rarely needed — prefer the decorator.

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
context.provide(extra_service)  # append more dependencies
context.without(SearchClient)   # drop instances of a type
context.clear()                 # remove everything
```

If an `Inject[T]` parameter has no default and no matching dependency is
found in context, execution raises `ValueError` rather than silently
passing `None`.

## Conditional availability and descriptions

Use `provided(...)` and `requires(...)` to expose a tool only when its
dependency is present (and, optionally, satisfies a predicate). Predicates
compose with `&`, `|`, and `~`:

```python
from agenttoolkit import provided, requires


@tools.action(
    "Issue a refund (admin only).",
    available_when=provided(BillingClient)
    & requires(UserInfo, predicate=lambda user: user.is_admin),
)
def refund(order_id: str, amount: float) -> str: ...
```

Use `description_from_context(...)` when a tool's description itself should
depend on context (e.g. embedding a resolved account name), with a fallback
for when the dependency isn't provided:

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

## Driving an agent loop

`Tools.get_schema(...)` returns the schema for every tool available in the
active (or a given) context; `Tools.execute(...)` dispatches a model-produced
call:

```python
openai_schemas = tools.get_schema(ToolSchemaFormat.OPENAI)
anthropic_schemas = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

result = await tools.execute("search", {"query": "tool middleware"}, context=context)
```

A typical loop confirms approval-gated tools before executing, and reports
status while a call is in flight:

```python
tool = tools.get(name)
if tool is not None and tool.requires_approval and not confirm(name, arguments):
    result = ActionResult.fail("Declined by user")
else:
    print(tool.format_status(arguments) if tool else name)
    result = await tools.execute(name, arguments, context=context)
```

`Tools.available(context=...)` returns the underlying `Tool` objects instead
of schemas — handy for printing a catalog of what's currently exposed
(`tool.name`, `tool.resolve_description(context)`, `tool.kind`, ...).

## Results (`ActionResult`)

```python
class ActionResult[ResultT](BaseModel):
    ok: bool
    result: ResultT | None = None
    error: str | None = None
```

Raw tool return values are wrapped as successful results automatically. A
tool may instead return an `ActionResult` directly — e.g. to fail without
raising, or to populate a typed result:

```python
WeatherActionResult = ActionResult[WeatherResult]


def get_weather(city: str) -> WeatherActionResult:
    temp_c = KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        return WeatherActionResult.fail(f"Unknown city: {city!r}")
    return WeatherActionResult.success(WeatherResult(city=city, temp_c=temp_c))
```

Because tool dispatch by name is dynamic and a registry can contain
heterogeneous return types, `Tools.execute()` always returns
`ActionResult[object]`; narrow `result` at the call site, or return a
specialized `ActionResult` directly from the tool as above.

`ActionResult` rejects unknown fields. When an application needs additional
result fields (trace IDs, citations, usage info), define them in a typed
subclass and wire it up via `Tools(result_type=...)` — every result the
middleware chain produces (validation failures, unknown-tool errors, the
internal-error fallback) is then built through that subclass too:

```python
class ProjectActionResult[ResultT](ActionResult[ResultT]):
    trace_id: str | None = None
    citations: tuple[str, ...] = ()


tools = Tools(result_type=ProjectActionResult[object])
```

## Middleware

Every call passes through a fixed core — error boundary, tool resolution,
argument validation — plus logging by default. Pass `middleware=` to run
additional steps *before* that core, e.g. a timeout:

```python
from agenttoolkit import ToolCall, ToolMiddleware


class TimeoutMiddleware(ToolMiddleware):
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    async def __call__(self, call: ToolCall, next):
        return await asyncio.wait_for(next(call), timeout=self._seconds)


tools = Tools(middleware=[TimeoutMiddleware(5.0)])
```

Supplying `middleware=` replaces the default logging step; add your own
logging middleware to the list if you still want it.

## Merging registries

Combine tools from multiple `Tools` instances — e.g. when composing a
registry from several feature modules:

```python
tools.merge(other_tools)               # raises on name collisions
tools.merge(other_tools, replace=True)  # other_tools wins on collisions
```

## Filesystem and shell primitives

`agenttoolkit.builtins` contains raw async implementations rather than a
predefined set of model-facing tools. Applications can use them directly,
inject them through `ToolContext`, or expose only the operations appropriate
for a particular agent.

```python
from agenttoolkit.builtins import (
    DockerSandbox,
    LocalWorkspace,
    SandboxPolicy,
)

workspace = LocalWorkspace("./project")
await workspace.write_file("src/example.py", "print('hello')\n")

entries = await workspace.list_dir("src")
source = await workspace.read_file(entries[0].path)

policy = SandboxPolicy.for_workspace(
    workspace.root,
    writable=True,
    enable_network_access=False,
)
sandbox = DockerSandbox("python:3.14-slim", policy)
result = await sandbox.execute("python src/example.py")
```

The `Workspace` port provides `read_file`, `write_file`, `edit_file`, `glob`,
`list_dir`, and `stat`. Exploration returns `Entry` values with a root-relative
POSIX path, directory and symlink flags, size, and modification time. Local
reads and writes are confined to the workspace root and bounded by a
configurable file-size limit.

The `Sandbox` port returns a common `SandboxResult` from all backends.
`SandboxPolicy` controls readable and writable paths, network access,
environment values, timeout, captured output, memory, process, and CPU limits.
`DockerSandbox` enforces all of these resource limits; `BubblewrapSandbox`
supports filesystem/network isolation and host-side timeout/output limits.
`UnsafeLocalSandbox` is useful for trusted commands but deliberately does not
claim to enforce path or network isolation.

## Skills

Local Agent Skills are discovered from directories containing one
subdirectory per skill, each with a `SKILL.md` file using YAML frontmatter
(`name`, `description`, and optional `license`, `compatibility`, `metadata`,
`allowed-tools`) followed by Markdown instructions:

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

```python
from agenttoolkit import Skills

skills = Skills.from_local_dir("./skills")

# Put the compact catalog in the agent's system prompt.
system_prompt = f"You are helpful.\n\n{skills.catalog()}"

# Progressive loading: full instructions + file listing for one skill...
instructions = skills.load("internet-research")

# ...then read a specific resource, or run a bundled script, on demand.
resource = skills.read_resource("internet-research", "references/guide.md")
output = await skills.run_script(
    "internet-research", "scripts/search.py", args=["python packaging"]
)
```

`Skills.from_local_dir` accepts multiple directories; a skill discovered
later overrides one with the same name from an earlier directory (logged as
a warning). `SKILL.md` is re-parsed from disk on each `load`/`get`, so
instructions can be edited without restarting the process.

Resource paths are confined to the selected skill's directory — absolute
paths and traversal outside it are rejected. Scripts run directly via their
interpreter (no shell) with a configurable timeout (default 60s); `.py`
scripts use the current Python interpreter, `.sh`/`.bash` require `bash` on
`PATH`. `run_script` never raises for script failures — it returns the
process's stdout, or an `Error: ...` string. Skill directories and their
scripts must still be treated as trusted code.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow
and conventions.

## License

MIT — see [LICENSE.md](LICENSE.md).
