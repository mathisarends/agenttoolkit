from pathlib import Path

import pytest

from agenttoolkit.builtins.fs import LocalWorkspace
from agenttoolkit.tools import ActionResult, ToolContext, ToolEffect, Tools
from experiments.tools import register_file_tools


@pytest.mark.asyncio
async def test_file_tools_read_write_and_edit_workspace_files(
    tmp_path: Path,
) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = Tools(context=ToolContext(workspace))
    register_file_tools(tools)

    written = await tools.execute(
        "write_file",
        {"path": "notes/message.txt", "content": "hello world"},
    )
    read = await tools.execute("read_file", {"path": "notes/message.txt"})
    edited = await tools.execute(
        "edit_file",
        {
            "path": "notes/message.txt",
            "old": "world",
            "new": "agent",
        },
    )

    assert written == ActionResult.success("Wrote notes/message.txt")
    assert read == ActionResult.success("hello world")
    assert edited == ActionResult.success(
        "Replaced 1 occurrence(s) in notes/message.txt"
    )
    assert await workspace.read_file("notes/message.txt") == "hello agent"


@pytest.mark.asyncio
async def test_file_tools_return_actionable_workspace_errors(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = Tools(context=ToolContext(workspace))
    register_file_tools(tools)

    missing = await tools.execute("read_file", {"path": "missing.txt"})
    outside = await tools.execute(
        "write_file",
        {"path": "../outside.txt", "content": "no"},
    )

    assert not missing.ok
    assert "missing.txt" in (missing.error or "")
    assert not outside.ok
    assert "outside workspace" in (outside.error or "")


def test_file_tools_expose_expected_metadata() -> None:
    tools = Tools()
    register_file_tools(tools)

    assert [tool.name for tool in tools] == ["read_file", "write_file", "edit_file"]
    assert [tool.effects for tool in tools] == [
        frozenset({ToolEffect.READS_WORKSPACE}),
        frozenset({ToolEffect.WRITES_WORKSPACE}),
        frozenset({ToolEffect.READS_WORKSPACE, ToolEffect.WRITES_WORKSPACE}),
    ]
