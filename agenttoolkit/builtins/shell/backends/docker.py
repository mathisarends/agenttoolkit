import asyncio
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from agenttoolkit.builtins.shell.policy import SandboxPolicy
from agenttoolkit.builtins.shell.sandbox import (
    SandboxError,
    SandboxResult,
    SandboxUnavailableError,
    run_process,
)


class DockerSandbox:
    def __init__(
        self,
        image: str,
        policy: SandboxPolicy | None = None,
        *,
        executable: str = "docker",
        shell: str = "/bin/sh",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        if not image.strip():
            raise ValueError("image must not be empty")
        self._image = image
        self._policy = policy or SandboxPolicy()
        self._executable = executable
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        container_name = f"agenttoolkit-{uuid.uuid4().hex}"
        argv = self.build_argv(
            command,
            cwd=cwd,
            env=env,
            interactive=stdin is not None,
            container_name=container_name,
        )
        try:
            result = await run_process(
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
        except SandboxUnavailableError:
            raise
        except asyncio.CancelledError:
            await asyncio.shield(self._remove_container(container_name))
            raise
        except BaseException:
            await self._remove_container(container_name)
            raise
        if result.timed_out:
            await self._remove_container(container_name)
        return result

    def build_argv(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        interactive: bool = False,
        container_name: str | None = None,
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError("command must not be empty")
        selected_cwd = self._policy.validate_working_directory(cwd)
        mounts = self._mounts(selected_cwd)
        container_cwd = _container_path(selected_cwd, mounts)

        argv = [
            self._executable,
            "run",
            "--rm",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev",
            "--workdir",
            str(container_cwd),
        ]
        if interactive:
            argv.append("-i")
        if container_name is not None:
            argv.extend(("--name", container_name))
        if not self._policy.enable_network_access:
            argv.extend(("--network", "none"))

        limits = self._policy.limits
        if limits.memory_bytes is not None:
            argv.extend(("--memory", str(limits.memory_bytes)))
        if limits.pids is not None:
            argv.extend(("--pids-limit", str(limits.pids)))
        if limits.cpus is not None:
            argv.extend(("--cpus", str(limits.cpus)))

        for source, target, writable in mounts:
            specification = f"type=bind,src={source},dst={target}"
            if not writable:
                specification += ",readonly"
            argv.extend(("--mount", specification))

        selected_env = dict(self._policy.environment)
        if env:
            selected_env.update(env)
        for key, value in selected_env.items():
            argv.extend(("--env", f"{key}={value}"))

        argv.extend((self._image, self._shell, *self._shell_arguments, command))
        return tuple(argv)

    def container_path(
        self,
        path: str | os.PathLike[str],
    ) -> PurePosixPath:
        working_directory = self._policy.validate_working_directory(None)
        requested = Path(path).expanduser()
        if not requested.is_absolute():
            requested = working_directory / requested
        requested = requested.resolve(strict=False)
        if (
            self._policy.readable_paths or self._policy.writable_paths
        ) and not self._policy.allows_read(requested):
            raise PermissionError(f"path is not allowed by sandbox policy: {requested}")
        return _container_path(requested, self._mounts(working_directory))

    async def _remove_container(self, name: str) -> None:
        try:
            await run_process(
                (self._executable, "rm", "--force", name),
                command=f"remove container {name}",
                cwd=None,
                env=None,
                stdin=None,
                timeout=10,
                max_output_bytes=64 * 1024,
            )
        except SandboxError:
            pass

    def _mounts(
        self,
        working_directory: Path,
    ) -> tuple[tuple[Path, PurePosixPath, bool], ...]:
        roots: list[tuple[Path, bool]] = []
        workspace = self._policy.working_directory or working_directory
        roots.append((workspace, self._policy.allows_write(workspace)))
        roots.extend((path, False) for path in self._policy.readable_paths)
        roots.extend((path, True) for path in self._policy.writable_paths)

        merged: dict[Path, bool] = {}
        for source, writable in roots:
            if not source.exists():
                raise FileNotFoundError(source)
            merged[source] = merged.get(source, False) or writable

        mounts: list[tuple[Path, PurePosixPath, bool]] = []
        extra_index = 0
        for source, writable in merged.items():
            if source == workspace:
                target = PurePosixPath("/workspace")
            else:
                target = PurePosixPath("/mnt") / f"path-{extra_index}"
                extra_index += 1
            mounts.append((source, target, writable))
        return tuple(mounts)


def _container_path(
    path: Path,
    mounts: tuple[tuple[Path, PurePosixPath, bool], ...],
) -> PurePosixPath:
    candidates: list[tuple[int, PurePosixPath]] = []
    for source, target, _ in mounts:
        try:
            relative = path.relative_to(source)
        except ValueError:
            continue
        candidates.append((len(source.parts), target.joinpath(*relative.parts)))
    if not candidates:
        raise PermissionError(f"path is not mounted in container: {path}")
    return max(candidates, key=lambda candidate: candidate[0])[1]
