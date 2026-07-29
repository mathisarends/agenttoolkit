from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from llmify import ChatCodex
from pydantic import BaseModel, Field

from agenttoolkit.builtins.shell import (
    BindMount,
    DockerSandbox,
    Sandbox,
    SandboxPolicy,
    UnsafeLocalSandbox,
)
from agenttoolkit.tools import ActionResult, Inject, ToolContext, Tools
from experiments.agent import Agent

DOCKER_IMAGE = "python:3.14-slim"
WORKSPACE = Path(__file__).parent / "sandbox_workspace"


def _build_sandbox(
    *,
    unsafe: bool,
    enable_network_access: bool = False,
    inherit_environment: Sequence[str] = (),
    mounts: Sequence[BindMount] = (),
) -> Sandbox:
    WORKSPACE.mkdir(exist_ok=True)
    policy = SandboxPolicy.for_workspace(
        WORKSPACE,
        writable=True,
        enable_network_access=unsafe or enable_network_access,
    )
    if unsafe:
        shell, shell_arguments = (
            ("cmd", ("/c",)) if os.name == "nt" else ("bash", ("-lc",))
        )
        return UnsafeLocalSandbox(
            policy=policy, shell=shell, shell_arguments=shell_arguments
        )
    return DockerSandbox(
        image=DOCKER_IMAGE,
        policy=policy,
        mounts=(
            BindMount.read_write(WORKSPACE, "/workspace"),
            *mounts,
        ),
        inherit_environment=inherit_environment,
        user="host",
    )


class BatchParams(BaseModel):
    command: str = Field(description="Command to run in the sandbox shell")


def _build_tools(sandbox: Sandbox, *, unsafe: bool) -> Tools:
    tools = Tools(context=ToolContext(sandbox))

    @tools.action(
        "Run a shell command in the sandbox and return its stdout/stderr",
        params=BatchParams,
        status=lambda params: f"Running: {params.command}",
        requires_approval=unsafe,
    )
    async def batch(params: BatchParams, sandbox: Inject[Sandbox]) -> ActionResult:
        result = await sandbox.execute(params.command)
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


def _confirm(name: str, arguments: dict) -> bool:
    answer = input(f"  ?? approve '{name}({arguments})'? [y/N] ").strip().lower()
    return answer == "y"


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
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
    sandbox = _build_sandbox(
        unsafe=args.unsafe,
        enable_network_access=args.network,
        inherit_environment=args.inherit_env,
        mounts=mounts,
    )
    tools = _build_tools(sandbox, unsafe=args.unsafe)

    model = ChatCodex.from_codex_cli(model="gpt-5.6-terra")
    agent = Agent(
        model,
        tools,
        system_prompt=(
            "You are a coding assistant with a single 'batch' tool that runs "
            "shell commands in a sandbox with Python 3.14 installed. Use it to "
            "inspect files, run scripts, and report results."
        ),
        on_tool_call=_on_tool_call,
        on_tool_result=_on_tool_result,
        confirm=_confirm,
    )

    mode = "UNSAFE (local)" if args.unsafe else f"sandboxed (docker: {DOCKER_IMAGE})"
    print(f"Chat gestartet [{mode}]. 'exit' zum Beenden.")
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
