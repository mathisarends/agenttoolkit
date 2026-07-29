import argparse
import asyncio
import sys
from pathlib import Path

from llmify import ChatCodex

from agenttoolkit.builtins.shell import Sandbox
from agenttoolkit.tools import ActionResult, Inject, ToolContext, Tools

from experiments.agent import Agent
from experiments.sandboxing import connected_sandbox

_WORKSPACE = Path(__file__).parent / "connected_workspace"


def _connected_tools(sandbox: Sandbox) -> Tools:
    tools = Tools(context=ToolContext(sandbox))

    @tools.action(
        "Run a Bash command in the connected-services sandbox.",
    )
    async def bash(command: str, sandbox: Inject[Sandbox]) -> ActionResult:
        result = await sandbox.execute(command)
        if not result.ok:
            return ActionResult.fail(
                f"exit={result.returncode} timed_out={result.timed_out}\n"
                f"{result.output}"
            )
        return ActionResult.success(result.output)

    return tools


def _on_tool_call(name: str, arguments: dict) -> None:
    print(f"  -> {name}({arguments})")


def _on_tool_result(name: str, result: ActionResult[object]) -> None:
    if result.ok:
        print(f"  <- {name}:\n{result.result}")
    else:
        print(f"  <- {name} FAILED:\n{result.error}")


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-spogo",
        action="store_true",
        help="fail at startup unless a host Spogo config can be mounted",
    )
    args = parser.parse_args()

    _WORKSPACE.mkdir(exist_ok=True)
    sandbox = connected_sandbox(
        _WORKSPACE,
        require_spogo=args.require_spogo,
    )
    tools = _connected_tools(sandbox)
    agent = Agent(
        ChatCodex.from_codex_cli(model="gpt-5.6-terra"),
        tools,
        system_prompt=(
            "You control connected home services through Bash in an isolated "
            "container. The installed CLIs are hueify, sonos, and spogo. "
            "Inspect their help when unsure. Never print credentials or config "
            "files, and prefer read-only status commands unless the user "
            "explicitly asks you to change something."
        ),
        on_tool_call=_on_tool_call,
        on_tool_result=_on_tool_result,
    )

    print("Connected chat gestartet [hueify, sonos, spogo]. " "'exit' zum Beenden.")
    while True:
        user_input = input("you> ").strip()
        if user_input in ("exit", "quit"):
            break
        if not user_input:
            continue

        reply = await agent.run(user_input)
        print(f"agent> {reply}")


if __name__ == "__main__":
    asyncio.run(main())
