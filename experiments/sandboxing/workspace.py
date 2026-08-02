import os
import tempfile
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from agenttoolkit.builtins.shell import (
    BindMount,
    CommandDefaults,
    CommandRunner,
    DockerSandbox,
    LocalShellRunner,
    SandboxPolicy,
)

DEFAULT_DOCKER_IMAGE = "python:3.14-slim"
_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "agenttoolkit-experiments"


def experiment_workspace(name: str) -> Path:
    workspace = _RUNTIME_ROOT / name
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@asynccontextmanager
async def workspace_runner(
    workspace: Path,
    *,
    unsafe: bool = False,
    image: str = DEFAULT_DOCKER_IMAGE,
    shell: str = "/bin/sh",
    enable_network_access: bool = False,
    inherit_environment: Sequence[str] = (),
    mounts: Sequence[BindMount] = (),
) -> AsyncGenerator[CommandRunner]:
    workspace.mkdir(parents=True, exist_ok=True)
    defaults = CommandDefaults(working_directory=workspace)
    if unsafe:
        local_shell, shell_arguments = (
            ("cmd", ("/c",)) if os.name == "nt" else ("bash", ("-lc",))
        )
        yield LocalShellRunner(
            defaults=defaults,
            shell=local_shell,
            shell_arguments=shell_arguments,
        )
        return

    sandbox = DockerSandbox(
        image=image,
        defaults=defaults,
        policy=SandboxPolicy.for_workspace(
            workspace,
            writable=True,
            enable_network_access=enable_network_access,
        ),
        mounts=mounts,
        inherit_environment=inherit_environment,
        user="host",
        shell=shell,
    )
    async with sandbox:
        yield sandbox
