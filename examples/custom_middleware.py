import asyncio
import time

from agenttk import Tools
from agenttk.tools.middleware import ToolCall, ToolHandler, ToolMiddleware
from agenttk.tools.results import ActionResult


class TimingMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> ActionResult[object]:
        started = time.perf_counter()
        result = await next(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"  [timing] {call.name} took {elapsed_ms:.2f}ms")
        return result


# Custom middleware runs inside the built-in error boundary, resolution and
# validation middlewares, so call.tool and call.params are already populated.
tools = Tools(middleware=[TimingMiddleware()])


@tools.action("Simulate slow work")
async def slow_task() -> str:
    await asyncio.sleep(0.05)
    return "done"


async def main() -> None:
    result = await tools.execute("slow_task")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
