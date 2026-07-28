from __future__ import annotations

from pathlib import Path

import pytest

from agenttoolkit import (
    Skills,
    ToolContext,
    Tools,
    parse_skill,
    register_skill_tools,
)


def make_skill(
    root: Path,
    *,
    name: str = "internet-research",
    description: str = "Research current sources.",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "license: Apache-2.0\n"
            "metadata:\n"
            "  author: test\n"
            '  version: "1.0"\n'
            "---\n"
            "# Research\n\nUse the bundled workflow.\n"
        ),
        encoding="utf-8",
    )
    return directory


def test_discovers_and_parses_skill_metadata(tmp_path: Path) -> None:
    directory = make_skill(tmp_path)

    skills = Skills.from_local_dir(tmp_path)
    skill = parse_skill(directory / "SKILL.md")

    assert len(skills) == 1
    assert skills.names() == ["internet-research"]
    assert skill.metadata == {"author": "test", "version": "1.0"}
    assert skill.license == "Apache-2.0"


def test_progressive_load_lists_resources_without_reading_them(
    tmp_path: Path,
) -> None:
    directory = make_skill(tmp_path)
    references = directory / "references"
    references.mkdir()
    (references / "guide.md").write_text("Loaded later.", encoding="utf-8")

    skills = Skills.from_local_dir(tmp_path)
    loaded = skills.load("internet-research")

    assert "Use the bundled workflow" in loaded
    assert "<file>references/guide.md</file>" in loaded
    assert "Loaded later." not in loaded
    assert skills.read_resource("internet-research", "references/guide.md") == (
        "Loaded later."
    )


def test_catalog_contains_only_name_and_description(tmp_path: Path) -> None:
    make_skill(tmp_path)

    catalog = Skills.from_local_dir(tmp_path).catalog()

    assert "<name>internet-research</name>" in catalog
    assert "<description>Research current sources.</description>" in catalog
    assert "Use the bundled workflow" not in catalog


def test_binary_resource_is_base64_and_escape_is_rejected(tmp_path: Path) -> None:
    directory = make_skill(tmp_path)
    (directory / "logo.bin").write_bytes(b"\xff\x00")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    skills = Skills.from_local_dir(tmp_path)

    assert skills.read_resource("internet-research", "logo.bin").startswith("base64: ")
    with pytest.raises(ValueError, match="outside skill"):
        skills.read_resource("internet-research", "../secret.txt")


def test_invalid_skill_name_is_rejected(tmp_path: Path) -> None:
    make_skill(tmp_path, name="invalid--name")

    with pytest.raises(ValueError, match="without leading"):
        Skills.from_local_dir(tmp_path)


@pytest.mark.asyncio
async def test_runs_python_script_without_shell(tmp_path: Path) -> None:
    directory = make_skill(tmp_path)
    scripts = directory / "scripts"
    scripts.mkdir()
    (scripts / "echo.py").write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    skills = Skills.from_local_dir(tmp_path)

    output = await skills.run_script(
        "internet-research",
        "scripts/echo.py",
        ["hello", "world"],
    )

    assert output == "hello|world"


@pytest.mark.asyncio
async def test_explicit_tool_bridge_uses_injected_skills(tmp_path: Path) -> None:
    directory = make_skill(tmp_path)
    (directory / "notes.md").write_text("Read me.", encoding="utf-8")
    skills = Skills.from_local_dir(tmp_path)
    registry = register_skill_tools(Tools())

    assert registry.get_schema() == []

    registry.set_context(ToolContext(skills))
    schemas = {schema.name for schema in registry.get_schema()}
    resource = await registry.execute(
        "read_skill_resource",
        {"name": "internet-research", "path": "notes.md"},
    )

    assert schemas == {"load_skill", "read_skill_resource", "run_skill_script"}
    assert resource.value == "Read me."
    assert registry.get("run_skill_script").kind == "destructive"


def test_script_tool_can_be_disabled(tmp_path: Path) -> None:
    skills = Skills.from_local_dir(make_skill(tmp_path).parent)
    registry = register_skill_tools(
        Tools(context=ToolContext(skills)),
        include_scripts=False,
    )

    assert {schema.name for schema in registry.get_schema()} == {
        "load_skill",
        "read_skill_resource",
    }
