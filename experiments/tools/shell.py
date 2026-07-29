from __future__ import annotations

from pydantic import BaseModel, Field

from agenttoolkit.builtins.shell import Sandbox
from agenttoolkit.tools import ActionResult, Inject, Tools


class ShellParams(BaseModel):
    command: str = Field(description="Shell command to run in the sandbox")


def register_shell_tool(
    tools: Tools,
    *,
    name: str = "bash",
    description: str = "Run a Bash command in the sandbox.",
    requires_approval: bool = False,
) -> None:
    @tools.action(
        description,
        name=name,
        params=ShellParams,
        status=lambda params: f"Running: {params.command}",
        requires_approval=requires_approval,
    )
    async def run_shell(
        params: ShellParams,
        sandbox: Inject[Sandbox],
    ) -> ActionResult:
        result = await sandbox.execute(params.command)
        if not result.ok:
            return ActionResult.fail(
                f"exit={result.returncode} timed_out={result.timed_out}\n"
                f"{result.output}"
            )
        return ActionResult.success(result.output)
