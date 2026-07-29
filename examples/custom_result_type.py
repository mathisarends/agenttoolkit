import asyncio
import uuid

from pydantic import Field

from agenttoolkit import ActionResult, Tools


# `= str` is repeated because PEP 696 defaults are declared per type
# parameter — a subclass does not inherit `ActionResult`'s default.
class TracedActionResult[ResultT = str](ActionResult[ResultT]):
    # Defaulted so middleware-generated failures (unknown tool, bad params,
    # ...) can build this envelope without knowing about tracing at all.
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# Passing `result_type` makes every automatically-wrapped return value, and
# every middleware failure (validation, unknown tool, ...), use this envelope.
tools = Tools(result_type=TracedActionResult[object])


@tools.action("Add two numbers")
def add(a: int, b: int) -> int:
    return a + b


async def main() -> None:
    result = await tools.execute("add", {"a": 2, "b": 3})
    print(result)

    failure = await tools.execute("unknown_tool", {})
    print(failure)


if __name__ == "__main__":
    asyncio.run(main())
