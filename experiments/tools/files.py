from pydantic import BaseModel, Field

from agenttoolkit.builtins.fs import Workspace
from agenttoolkit.tools import Inject, ToolEffect, Tools


class ReadFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")


class WriteFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")
    content: str = Field(description="Complete UTF-8 file content")


class EditFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")
    old: str = Field(description="Exact text to replace")
    new: str = Field(description="Replacement text")
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence instead of requiring exactly one",
    )


def register_file_tools(tools: Tools) -> None:
    @tools.action(
        "Read a UTF-8 text file from the workspace.",
        params=ReadFileParams,
        status="Reading {path}",
        effects=(ToolEffect.READS_WORKSPACE,),
    )
    async def read_file(
        params: ReadFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        return await workspace.read_file(params.path)

    @tools.action(
        "Write the complete UTF-8 content of a file in the workspace. "
        "Missing parent directories are created.",
        params=WriteFileParams,
        status="Writing {path}",
        effects=(ToolEffect.WRITES_WORKSPACE,),
    )
    async def write_file(
        params: WriteFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        await workspace.write_file(params.path, params.content)
        return f"Wrote {params.path}"

    @tools.action(
        "Replace exact text in a UTF-8 file in the workspace. By default the "
        "old text must occur exactly once.",
        params=EditFileParams,
        status="Editing {path}",
        effects=(ToolEffect.READS_WORKSPACE, ToolEffect.WRITES_WORKSPACE),
    )
    async def edit_file(
        params: EditFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        replacements = await workspace.edit_file(
            params.path,
            params.old,
            params.new,
            replace_all=params.replace_all,
        )
        return f"Replaced {replacements} occurrence(s) in {params.path}"
