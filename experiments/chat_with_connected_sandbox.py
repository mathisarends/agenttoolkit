import argparse
import asyncio
from pathlib import Path, PurePosixPath

from llmify import ChatCodex

from agenttoolkit import SkillRefreshMiddleware, Skills
from agenttoolkit.builtins.fs import LocalWorkspace
from agenttoolkit.builtins.shell import BindMount
from agenttoolkit.tools import ToolContext, Tools
from agenttoolkit.tools.middleware import CallLoggingMiddleware
from experiments.agent import Agent
from experiments.environments import Console
from experiments.sandboxing import connected_sandbox, experiment_workspace
from experiments.tools import (
    register_file_tools,
    register_shell_tool,
    register_skill_loader,
)

SKILLS_DIR = Path(__file__).parent / "skills"
CONTAINER_SKILLS_DIR = PurePosixPath("/skills")


def _system_prompt(skills: Skills) -> str:
    return (
        "You control connected home services through Bash in an isolated "
        "container. The installed CLIs are openhue, sonos, and spogo. "
        "Inspect their help when unsure. Never print credentials or config "
        "files, and prefer read-only status commands unless the user "
        "explicitly asks you to change something.\n\n"
        "You also have progressively disclosed skills. The catalog below "
        "contains only skill names and descriptions. When a request matches a "
        "skill, call load_skill before acting and follow its instructions. "
        "Skill files are writable under /skills. When the user asks you to "
        "capture a reusable workflow, load skill-creator and create or update "
        "the skill there. Inspect an existing skill before changing it.\n\n"
        f"{skills.render_prompt()}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-spogo",
        action="store_true",
        help="fail at startup unless a host Spogo config can be mounted",
    )
    args = parser.parse_args()

    skills = Skills.from_local_dir(SKILLS_DIR)
    workspace = LocalWorkspace(experiment_workspace("connected"))
    sandbox = connected_sandbox(
        workspace.root,
        require_spogo=args.require_spogo,
        mounts=(BindMount.read_write(SKILLS_DIR, CONTAINER_SKILLS_DIR),),
    )
    tools = Tools(
        context=ToolContext(sandbox, skills, workspace),
        middleware=[
            SkillRefreshMiddleware(),
            CallLoggingMiddleware(),
        ],
    )
    register_skill_loader(tools, container_root=CONTAINER_SKILLS_DIR)
    register_file_tools(tools)
    register_shell_tool(
        tools,
        description=(
            "Run a Bash command in the connected-services sandbox. The shared "
            "working directory is /workspace; skills can be read and written "
            "under /skills."
        ),
    )
    console = Console(tools)
    agent = Agent(
        ChatCodex.from_cli(model="gpt-5.6-sol", on_retry=console.on_retry),
        tools,
        system_prompt=lambda: _system_prompt(skills),
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
    )

    await console.run(
        agent,
        (
            "Connected chat gestartet "
            f"[openhue, sonos, spogo; Skills: {', '.join(skills.names())}]. "
            "'exit' zum Beenden."
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
