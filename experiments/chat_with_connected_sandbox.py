import argparse
import asyncio

from llmify import ChatCodex

from agenttoolkit.tools import ToolContext, Tools
from experiments.agent import Agent
from experiments.environments import Console
from experiments.sandboxing import connected_sandbox, experiment_workspace
from experiments.tools import register_shell_tool


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-spogo",
        action="store_true",
        help="fail at startup unless a host Spogo config can be mounted",
    )
    args = parser.parse_args()

    sandbox = connected_sandbox(
        experiment_workspace("connected"),
        require_spogo=args.require_spogo,
    )
    tools = Tools(context=ToolContext(sandbox))
    register_shell_tool(
        tools,
        description="Run a Bash command in the connected-services sandbox.",
    )
    console = Console(tools)
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
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
    )

    await console.run(
        agent,
        "Connected chat gestartet [hueify, sonos, spogo]. 'exit' zum Beenden.",
    )


if __name__ == "__main__":
    asyncio.run(main())
