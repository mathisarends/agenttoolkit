import argparse
import asyncio
import logging
from pathlib import Path, PurePosixPath

from llmify import ChatCodex

from agenttoolkit import Skills
from agenttoolkit.builtins.shell import BindMount
from agenttoolkit.tools import ToolContext, Tools
from experiments.agent import Agent
from experiments.environments import Console
from experiments.sandboxing import experiment_workspace, workspace_sandbox
from experiments.tools import register_shell_tool, register_skill_loader

SKILLS_DIR = Path(__file__).parent / "skills"
CONTAINER_SKILLS_DIR = PurePosixPath("/skills")

logger = logging.getLogger(__name__)


def _system_prompt(skills: Skills) -> str:
    return (
        "You are a helpful assistant with Bash and progressively disclosed "
        "skills. The catalog below contains only skill names and descriptions. "
        "When a request matches a skill, call load_skill before answering. "
        "Follow the loaded instructions and use Bash to read only the referenced "
        "resources or run the referenced scripts. Do not read SKILL.md with Bash.\n\n"
        f"{skills.render_prompt()}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        help="run a single prompt instead of starting the interactive chat",
    )
    args = parser.parse_args()

    skills = Skills.from_local_dir(SKILLS_DIR)
    sandbox = workspace_sandbox(
        experiment_workspace("bash-and-skills"),
        mounts=(BindMount.read_only(SKILLS_DIR, CONTAINER_SKILLS_DIR),),
        shell="/bin/bash",
    )
    tools = Tools(context=ToolContext(sandbox, skills))
    register_skill_loader(tools, container_root=CONTAINER_SKILLS_DIR)
    register_shell_tool(
        tools,
        description=(
            "Run a Bash command in the sandbox. Skill files are read-only under "
            "/skills; the writable working directory is /workspace."
        ),
    )

    console = Console(tools)
    agent = Agent(
        ChatCodex.from_codex_cli(model="gpt-5.6-terra"),
        tools,
        system_prompt=_system_prompt(skills),
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
    )
    await console.run(
        agent,
        f"Skills-Chat gestartet [{', '.join(skills.names())}]. " "'exit' zum Beenden.",
        prompt=args.prompt,
    )


if __name__ == "__main__":
    asyncio.run(main())
