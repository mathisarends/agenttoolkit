from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agenttoolkit.builtins.shell import (
    BindMount,
    DockerSandbox,
    Sandbox,
    SandboxPolicy,
    UnsafeLocalSandbox,
)

DEFAULT_DOCKER_IMAGE = "python:3.14-slim"
_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "agenttoolkit-experiments"


def experiment_workspace(name: str) -> Path:
    workspace = _RUNTIME_ROOT / name
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def workspace_sandbox(
    workspace: Path,
    *,
    unsafe: bool = False,
    image: str = DEFAULT_DOCKER_IMAGE,
    shell: str = "/bin/sh",
    enable_network_access: bool = False,
    inherit_environment: Sequence[str] = (),
    mounts: Sequence[BindMount] = (),
) -> Sandbox:
    workspace.mkdir(parents=True, exist_ok=True)
    policy = SandboxPolicy.for_workspace(
        workspace,
        writable=True,
        enable_network_access=unsafe or enable_network_access,
    )
    if unsafe:
        local_shell, shell_arguments = (
            ("cmd", ("/c",)) if os.name == "nt" else ("bash", ("-lc",))
        )
        return UnsafeLocalSandbox(
            policy=policy,
            shell=local_shell,
            shell_arguments=shell_arguments,
        )
    return DockerSandbox(
        image=image,
        policy=policy,
        mounts=mounts,
        inherit_environment=inherit_environment,
        user="host",
        shell=shell,
    )
