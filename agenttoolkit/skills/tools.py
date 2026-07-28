from pydantic import BaseModel, ConfigDict, Field

from agenttoolkit.skills.collection import Skills
from agenttoolkit.tools import (
    ActionKind,
    ActionResult,
    Inject,
    Tools,
    requires,
)


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoadSkillParams(_Params):
    name: str = Field(description="Name of the skill, exactly as listed.")


class ReadSkillResourceParams(LoadSkillParams):
    path: str = Field(description="Bundled path relative to the skill directory.")


class RunSkillScriptParams(ReadSkillResourceParams):
    args: list[str] = Field(
        default_factory=list,
        description="Arguments passed directly to the script.",
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Timeout in seconds.",
    )


def register_skill_tools(
    registry: Tools,
    *,
    include_scripts: bool = True,
) -> Tools:
    available = requires(Skills, predicate=lambda skills: skills.size > 0)

    @registry.action(
        "Load a skill's instructions and list its bundled files. "
        "Call this before using a skill.",
        name="load_skill",
        params=LoadSkillParams,
        kind=ActionKind.READ,
        available_when=available,
        tags=["skills"],
    )
    def load_skill(
        params: LoadSkillParams,
        skills: Inject[Skills],
    ) -> ActionResult:
        return ActionResult.success(skills.load(params.name))

    @registry.action(
        "Read one file bundled with a skill, as listed by load_skill.",
        name="read_skill_resource",
        params=ReadSkillResourceParams,
        kind=ActionKind.READ,
        available_when=available,
        tags=["skills"],
    )
    def read_skill_resource(
        params: ReadSkillResourceParams,
        skills: Inject[Skills],
    ) -> ActionResult:
        return ActionResult.success(skills.read_resource(params.name, params.path))

    if include_scripts:

        @registry.action(
            "Run one trusted script bundled with a skill. The script runs in the "
            "skill directory and no shell is involved.",
            name="run_skill_script",
            params=RunSkillScriptParams,
            kind=ActionKind.DESTRUCTIVE,
            available_when=available,
            tags=["skills", "code-execution"],
        )
        async def run_skill_script(
            params: RunSkillScriptParams,
            skills: Inject[Skills],
        ) -> ActionResult:
            output = await skills.run_script(
                params.name,
                params.path,
                params.args,
                params.timeout,
            )
            return ActionResult.success(output)

    return registry
