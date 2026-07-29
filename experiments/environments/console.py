from __future__ import annotations

import sys
from typing import Any

from agenttoolkit.tools import ActionResult, Tool, ToolContext, Tools
from experiments.agent import Agent


class Console:
    """Shared terminal UI for the interactive experiments."""

    def __init__(
        self,
        tools: Tools,
        *,
        context: ToolContext | None = None,
    ) -> None:
        self._tools = tools
        self._context = context

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        tool: Tool | None = self._tools.get(name)
        status = tool.format_status(arguments) if tool else None
        label = f" ({status})" if status else ""
        print(f"  -> {name}({arguments}){label}")

    def on_tool_result(
        self,
        name: str,
        result: ActionResult[object],
    ) -> None:
        if result.ok:
            print(f"  <- {name}:\n{result.result}")
        else:
            print(f"  <- {name} FAILED:\n{result.error}")

    def confirm(self, name: str, arguments: dict[str, Any]) -> bool:
        answer = input(f"  ?? approve '{name}({arguments})'? [y/N] ")
        return answer.strip().lower() == "y"

    def print_tools(self) -> None:
        print("Registered tools (available in current context):")
        for tool in self._tools.get_available():
            flags = []
            if tool.requires_approval:
                flags.append("requires_approval")
            if tool.available_when is not None:
                flags.append("gated")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            print(
                f"  - {tool.name}: "
                f"{tool.resolve_description(self._context)}{flag_text}"
            )
        print()

    async def run(
        self,
        agent: Agent,
        banner: str,
        *,
        prompt: str | None = None,
    ) -> None:
        _configure_stdout()
        if prompt:
            print(f"agent> {await agent.run(prompt)}")
            return

        print(banner)
        while True:
            user_input = input("you> ").strip()
            if user_input in ("exit", "quit"):
                return
            if not user_input:
                continue
            print(f"agent> {await agent.run(user_input)}")


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
