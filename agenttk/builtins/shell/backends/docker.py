import asyncio
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Self

from agenttk.builtins.shell.policy import SandboxPolicy
from agenttk.builtins.shell.sandbox import (
    SandboxError,
    SandboxResult,
    SandboxUnavailableError,
    run_process,
)


class DockerNetworkMode(StrEnum):
    BRIDGE = "bridge"
    HOST = "host"


@dataclass(frozen=True, slots=True, init=False)
class BindMount:
    source: Path
    target: PurePosixPath
    writable: bool

    def __init__(
        self,
        source: str | os.PathLike[str],
        target: str | PurePosixPath,
        *,
        writable: bool = False,
    ) -> None:
        normalized_source = Path(source).expanduser().resolve(strict=False)
        normalized_target = PurePosixPath(target)
        if (
            not normalized_target.is_absolute()
            or normalized_target == PurePosixPath("/")
            or ".." in normalized_target.parts
        ):
            raise ValueError(
                f"mount target must be an absolute container path below '/': {target!r}"
            )
        object.__setattr__(self, "source", normalized_source)
        object.__setattr__(self, "target", normalized_target)
        object.__setattr__(self, "writable", writable)

    @classmethod
    def read_only(
        cls,
        source: str | os.PathLike[str],
        target: str | PurePosixPath,
    ) -> Self:
        return cls(source, target)

    @classmethod
    def read_write(
        cls,
        source: str | os.PathLike[str],
        target: str | PurePosixPath,
    ) -> Self:
        return cls(source, target, writable=True)


class DockerSandbox:
    def __init__(
        self,
        image: str,
        policy: SandboxPolicy | None = None,
        *,
        mounts: Sequence[BindMount] = (),
        inherit_environment: Sequence[str] = (),
        user: str | None = None,
        network_mode: DockerNetworkMode | None = None,
        executable: str = "docker",
        shell: str = "/bin/sh",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        if not image.strip():
            raise ValueError("image must not be empty")
        self._image = image
        self._policy = policy or SandboxPolicy()
        self._mount_definitions = _validate_mounts(mounts)
        self._inherit_environment = _validate_environment_names(inherit_environment)
        if user is not None and not user.strip():
            raise ValueError("user must not be empty")
        self._user = user
        if network_mode is not None:
            if not isinstance(network_mode, DockerNetworkMode):
                raise TypeError("network mode must be a DockerNetworkMode")
            if not self._policy.enable_network_access:
                raise ValueError(
                    "network mode requires network access to be enabled by policy"
                )
        self._network_mode = network_mode
        self._executable = executable
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    @property
    def mounts(self) -> tuple[BindMount, ...]:
        return self._mount_definitions

    @property
    def inherit_environment(self) -> tuple[str, ...]:
        return self._inherit_environment

    @property
    def user(self) -> str | None:
        return self._user

    @property
    def network_mode(self) -> DockerNetworkMode | None:
        return self._network_mode

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        container_name = f"agenttk-{uuid.uuid4().hex}"
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
        if self._network_mode is not None:
            argv.extend(("--network", self._network_mode.value))
        elif not self._policy.enable_network_access:
            argv.extend(("--network", "none"))
        if selected_user := _resolve_user(self._user):
            argv.extend(("--user", selected_user))

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
        for key in self._inherit_environment:
            if key in selected_env:
                continue
            if key not in os.environ:
                raise ValueError(f"host environment variable is not set: {key}")
            argv.extend(("--env", key))
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

        explicit_sources = {mount.source for mount in self._mount_definitions}
        mounts: list[tuple[Path, PurePosixPath, bool]] = []
        extra_index = 0
        for source, writable in merged.items():
            if source in explicit_sources:
                continue
            if source == workspace:
                target = PurePosixPath("/workspace")
            else:
                target = PurePosixPath("/mnt") / f"path-{extra_index}"
                extra_index += 1
            mounts.append((source, target, writable))
        mounts.extend(
            (mount.source, mount.target, mount.writable)
            for mount in self._mount_definitions
        )

        targets: dict[PurePosixPath, Path] = {}
        for source, target, _ in mounts:
            if not source.exists():
                raise FileNotFoundError(source)
            if existing := targets.get(target):
                raise ValueError(
                    f"mount target {target} is used by both {existing} and {source}"
                )
            targets[target] = source
        mounts.sort(key=lambda mount: len(mount[1].parts))
        return tuple(mounts)


def _validate_mounts(mounts: Sequence[BindMount]) -> tuple[BindMount, ...]:
    normalized = tuple(mounts)
    sources: set[Path] = set()
    targets: set[PurePosixPath] = set()
    for mount in normalized:
        if mount.source in sources:
            raise ValueError(
                f"mount source is configured more than once: {mount.source}"
            )
        if mount.target in targets:
            raise ValueError(
                f"mount target is configured more than once: {mount.target}"
            )
        sources.add(mount.source)
        targets.add(mount.target)
    return normalized


def _validate_environment_names(names: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for name in names:
        if not name or "=" in name or "\x00" in name:
            raise ValueError(f"invalid environment variable name: {name!r}")
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _resolve_user(user: str | None) -> str | None:
    if user != "host":
        return user
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return f"{getuid()}:{getgid()}"


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
