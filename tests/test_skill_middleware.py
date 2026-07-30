import logging
from pathlib import Path

import pytest

from agenttoolkit import (
    ActionResult,
    SkillRefreshMiddleware,
    Skills,
    ToolEffect,
    Tools,
)


def skill_source(
    name: str,
    description: str = "A test skill.",
) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n"
        "# Test\n\n"
        "Follow the test workflow.\n"
    )


def make_skill(root: Path, name: str = "existing") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        skill_source(name),
        encoding="utf-8",
    )
    return directory


@pytest.mark.asyncio
async def test_writing_tool_refreshes_and_returns_new_catalog(tmp_path: Path) -> None:
    make_skill(tmp_path)
    skills = Skills.from_local_dir(tmp_path)
    tools = Tools(middleware=[SkillRefreshMiddleware(skills)])

    @tools.action("Write a skill", effects=(ToolEffect.WRITES_WORKSPACE,))
    def write_skill() -> str:
        make_skill(tmp_path, "created")
        return "written"

    result = await tools.execute("write_skill")

    assert result == ActionResult.success("written")
    assert skills.names() == ["created", "existing"]
    assert skills.revision == 1


@pytest.mark.asyncio
async def test_tool_without_write_effect_does_not_refresh_registry(
    tmp_path: Path,
) -> None:
    make_skill(tmp_path)
    skills = Skills.from_local_dir(tmp_path)
    tools = Tools(middleware=[SkillRefreshMiddleware(skills)])

    @tools.action("Write without declaring the effect")
    def other_tool() -> str:
        make_skill(tmp_path, "created")
        return "written"

    result = await tools.execute("other_tool")

    assert result == ActionResult.success("written")
    assert skills.names() == ["existing"]


@pytest.mark.asyncio
async def test_custom_predicate_selects_tools(tmp_path: Path) -> None:
    make_skill(tmp_path)
    skills = Skills.from_local_dir(tmp_path)
    tools = Tools(
        middleware=[
            SkillRefreshMiddleware(skills, when=lambda tool: "skills" in tool.tags),
        ]
    )

    @tools.action("Write a skill", tags=["skills"])
    def write_skill() -> str:
        make_skill(tmp_path, "created")
        return "written"

    result = await tools.execute("write_skill")

    assert result == ActionResult.success("written")
    assert skills.names() == ["created", "existing"]


@pytest.mark.asyncio
async def test_invalid_edit_reports_error_and_keeps_active_registry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = make_skill(tmp_path)
    skills = Skills.from_local_dir(tmp_path)
    tools = Tools(middleware=[SkillRefreshMiddleware(skills)])

    @tools.action("Write an invalid skill", effects=(ToolEffect.WRITES_WORKSPACE,))
    def write_skill() -> str:
        (directory / "SKILL.md").write_text(
            "# Missing frontmatter",
            encoding="utf-8",
        )
        return "written"

    with caplog.at_level(logging.ERROR):
        result = await tools.execute("write_skill")

    assert result == ActionResult.success("written")
    assert skills.names() == ["existing"]
    assert skills.revision == 0
    assert "Skill refresh failed after tool 'write_skill'" in caplog.text
    assert "must start with YAML frontmatter" in caplog.text


@pytest.mark.asyncio
async def test_failed_writing_tool_still_reports_catalog_update(
    tmp_path: Path,
) -> None:
    make_skill(tmp_path)
    skills = Skills.from_local_dir(tmp_path)
    tools = Tools(middleware=[SkillRefreshMiddleware(skills)])

    @tools.action("Write and fail", effects=(ToolEffect.WRITES_WORKSPACE,))
    def write_skill() -> ActionResult:
        make_skill(tmp_path, "created")
        return ActionResult.fail("command failed")

    result = await tools.execute("write_skill")

    assert result == ActionResult.fail("command failed")
    assert skills.names() == ["created", "existing"]
