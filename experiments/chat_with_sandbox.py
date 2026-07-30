import argparse
import asyncio

from agenttoolkit.builtins.shell import BindMount
from agenttoolkit.tools import ToolContext, Tools
from experiments.agent import Agent
from experiments.environments import Console
from experiments.model import experiment_model
from experiments.sandboxing import (
    DEFAULT_DOCKER_IMAGE,
    experiment_workspace,
    workspace_sandbox,
)
from experiments.tools import register_shell_tool


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="run commands directly on the host instead of the Docker sandbox",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="allow network access inside the Docker sandbox",
    )
    parser.add_argument(
        "--inherit-env",
        action="append",
        default=[],
        metavar="NAME",
        help="forward a host environment variable into Docker; repeatable",
    )
    parser.add_argument(
        "--mount-ro",
        action="append",
        default=[],
        nargs=2,
        metavar=("HOST_PATH", "CONTAINER_PATH"),
        help="add a read-only Docker bind mount; repeatable",
    )
    parser.add_argument(
        "--mount-rw",
        action="append",
        default=[],
        nargs=2,
        metavar=("HOST_PATH", "CONTAINER_PATH"),
        help="add a writable Docker bind mount with host write-back; repeatable",
    )
    args = parser.parse_args()

    mounts = (
        *(BindMount.read_only(source, target) for source, target in args.mount_ro),
        *(BindMount.read_write(source, target) for source, target in args.mount_rw),
    )
    sandbox = workspace_sandbox(
        experiment_workspace("sandbox"),
        unsafe=args.unsafe,
        enable_network_access=args.network,
        inherit_environment=args.inherit_env,
        mounts=mounts,
    )
    tools = Tools(context=ToolContext(sandbox))
    register_shell_tool(
        tools,
        name="batch",
        description="Run a shell command in the sandbox and return its output.",
        requires_approval=args.unsafe,
    )
    console = Console(tools)

    model = experiment_model("gpt-5.6-sol", on_retry=console.on_retry)
    agent = Agent(
        model,
        tools,
        system_prompt=(
            "You are a coding assistant with a single 'batch' tool that runs "
            "shell commands in a sandbox with Python 3.14 installed. Use it to "
            "inspect files, run scripts, and report results."
        ),
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
        confirm=console.confirm,
    )

    mode = (
        "UNSAFE (local)"
        if args.unsafe
        else f"sandboxed (docker: {DEFAULT_DOCKER_IMAGE})"
    )
    await console.run(agent, f"Chat gestartet [{mode}]. 'exit' zum Beenden.")


if __name__ == "__main__":
    asyncio.run(main())
