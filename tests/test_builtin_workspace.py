from __future__ import annotations

from pathlib import Path

import pytest

from agenttoolkit.builtins.fs import (
    EditError,
    Entry,
    FileTooLargeError,
    LocalWorkspace,
    PathOutsideWorkspaceError,
    Workspace,
)


@pytest.mark.asyncio
async def test_workspace_file_operations_and_exploration(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    assert isinstance(workspace, Workspace)

    await workspace.write_file("src/z.py", "first\n")
    await workspace.write_file("src/a.py", "alpha\n")
    assert await workspace.read_file("src/z.py") == "first\n"
    assert await workspace.edit_file("src/z.py", "first", "second") == 1
    assert await workspace.read_file("src/z.py") == "second\n"

    shallow = await workspace.list_dir()
    assert [(entry.path, entry.is_dir) for entry in shallow] == [("src", True)]
    recursive = await workspace.list_dir(recursive=True, limit=2)
    assert [entry.path for entry in recursive] == ["src", "src/a.py"]

    matches = await workspace.glob("**/*.py")
    assert [entry.path for entry in matches] == ["src/a.py", "src/z.py"]
    assert all(isinstance(entry, Entry) for entry in matches)
    assert matches[0].size == 6
    assert matches[0].modified is not None

    entry = await workspace.stat("src/a.py")
    assert entry is not None
    assert not entry.is_dir
    assert not entry.is_symlink
    assert await workspace.stat("missing") is None


@pytest.mark.asyncio
async def test_workspace_edit_is_deliberately_exact(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    await workspace.write_file("values.txt", "x x")

    with pytest.raises(EditError, match="occurs 2 times"):
        await workspace.edit_file("values.txt", "x", "y")
    assert await workspace.edit_file("values.txt", "x", "y", replace_all=True) == 2
    assert await workspace.read_file("values.txt") == "y y"

    with pytest.raises(EditError, match="must not be empty"):
        await workspace.edit_file("values.txt", "", "z")
    with pytest.raises(EditError, match="was not found"):
        await workspace.edit_file("values.txt", "absent", "z")


@pytest.mark.asyncio
async def test_workspace_rejects_escape_and_oversized_files(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path / "root", max_file_bytes=3)

    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.write_file("../outside.txt", "x")
    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.glob("../*")
    with pytest.raises(ValueError, match="must not be empty"):
        await workspace.glob("")
    with pytest.raises(FileTooLargeError):
        await workspace.write_file("large.txt", "four")

    (workspace.root / "large.txt").write_text("four")
    with pytest.raises(FileTooLargeError):
        await workspace.read_file("large.txt")
    with pytest.raises(FileNotFoundError):
        await workspace.write_file("missing/file.txt", "ok", create_parents=False)


@pytest.mark.asyncio
async def test_workspace_directory_and_symlink_metadata(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path / "root")
    await workspace.write_file("data/file.txt", "data")

    with pytest.raises(IsADirectoryError):
        await workspace.write_file("data", "no")
    with pytest.raises(NotADirectoryError):
        await workspace.list_dir("data/file.txt")
    with pytest.raises(ValueError, match="non-negative"):
        await workspace.list_dir(limit=-1)

    link = workspace.root / "link"
    try:
        link.symlink_to(workspace.root / "data", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks is not permitted")

    entry = await workspace.stat("link")
    assert entry is not None
    assert entry.is_symlink
    assert entry.is_dir


def test_workspace_constructor_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        LocalWorkspace(tmp_path, max_file_bytes=0)

    file_root = tmp_path / "file"
    file_root.write_text("content")
    with pytest.raises(NotADirectoryError):
        LocalWorkspace(file_root)
