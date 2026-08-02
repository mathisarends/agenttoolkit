import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from agenttoolkit.builtins.shell.policy import SandboxPolicy
from agenttoolkit.builtins.shell.sandbox import (
    SandboxLifecycle,
    SandboxResult,
    SandboxUnavailableError,
    run_process,
)


class BubblewrapSandbox(SandboxLifecycle):
    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        *,
        executable: str = "bwrap",
        shell: str = "/bin/sh",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        super().__init__()
        self._policy = policy or SandboxPolicy()
        self._executable = executable
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    @property
    def available(self) -> bool:
        return os.name == "posix" and shutil.which(self._executable) is not None

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        self._require_open()
        if not self.available:
            raise SandboxUnavailableError(
                "bubblewrap is only available on Linux with bwrap installed"
            )
        argv = self.build_argv(command, cwd=cwd, env=env)
        return await run_process(
            argv,
            command=command,
            cwd=None,
            env=None,
            stdin=stdin,
            timeout=(
                self._policy.limits.timeout_seconds if timeout is None else timeout
            ),
            max_output_bytes=self._policy.limits.max_output_bytes,
        )

    def build_argv(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError("command must not be empty")
        limits = self._policy.limits
        unsupported = [
            name
            for name, value in (
                ("memory_bytes", limits.memory_bytes),
                ("pids", limits.pids),
                ("cpus", limits.cpus),
            )
            if value is not None
        ]
        if unsupported:
            names = ", ".join(unsupported)
            raise ValueError(f"bubblewrap cannot enforce these limits: {names}")

        selected_cwd = self._policy.validate_working_directory(cwd)
        mounts = self._mounts(selected_cwd)
        argv = [
            self._executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--tmpfs",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--dir",
            "/tmp",
        ]
        if self._policy.enable_network_access:
            argv.append("--share-net")

        for system_path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
            if Path(system_path).exists():
                argv.extend(("--ro-bind", system_path, system_path))

        destinations = _destination_directories(source for source, _ in mounts)
        for destination in destinations:
            argv.extend(("--dir", str(destination)))
        for source, writable in mounts:
            option = "--bind" if writable else "--ro-bind"
            argv.extend((option, str(source), str(source)))

        selected_env = {
            "HOME": "/tmp",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            **self._policy.environment,
        }
        if env:
            selected_env.update(env)
        argv.append("--clearenv")
        for key, value in selected_env.items():
            argv.extend(("--setenv", key, value))

        argv.extend(
            (
                "--chdir",
                str(selected_cwd),
                self._shell,
                *self._shell_arguments,
                command,
            )
        )
        return tuple(argv)

    def _mounts(self, working_directory: Path) -> tuple[tuple[Path, bool], ...]:
        roots: dict[Path, bool] = {}
        workspace = self._policy.working_directory or working_directory
        roots[workspace] = self._policy.allows_write(workspace)
        for path in self._policy.readable_paths:
            roots.setdefault(path, False)
        for path in self._policy.writable_paths:
            roots[path] = True
        for source in roots:
            if not source.exists():
                raise FileNotFoundError(source)
        return tuple(roots.items())


def _destination_directories(paths: Iterable[Path]) -> list[Path]:
    directories: set[Path] = set()
    for source in paths:
        path = source if source.is_dir() else source.parent
        while path != path.parent and str(path) not in {
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/lib64",
        }:
            directories.add(path)
            path = path.parent
    return sorted(directories, key=lambda item: len(item.parts))
