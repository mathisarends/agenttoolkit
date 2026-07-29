import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Self


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    timeout_seconds: float | None = 60.0
    max_output_bytes: int | None = 1024 * 1024
    memory_bytes: int | None = None
    pids: int | None = None
    cpus: float | None = None

    def __post_init__(self) -> None:
        _positive("timeout_seconds", self.timeout_seconds)
        _positive("max_output_bytes", self.max_output_bytes)
        _positive("memory_bytes", self.memory_bytes)
        _positive("pids", self.pids)
        _positive("cpus", self.cpus)


def _positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be positive or None")


type PathInput = Path | str | os.PathLike[str]


@dataclass(frozen=True, slots=True, init=False)
class SandboxPolicy:
    working_directory: Path | None
    readable_paths: tuple[Path, ...]
    writable_paths: tuple[Path, ...]
    enable_network_access: bool
    limits: SandboxLimits
    environment: Mapping[str, str]

    def __init__(
        self,
        working_directory: PathInput | None = None,
        readable_paths: Sequence[PathInput] = (),
        writable_paths: Sequence[PathInput] = (),
        enable_network_access: bool = False,
        limits: SandboxLimits | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        normalized_working_directory = _normalize_optional(working_directory)
        readable = _normalize_many(readable_paths)
        writable = _normalize_many(writable_paths)

        if normalized_working_directory is not None and not _contained_by(
            normalized_working_directory, (*readable, *writable)
        ):
            readable = (*readable, normalized_working_directory)

        normalized_environment: dict[str, str] = {}
        for key, value in (environment or {}).items():
            key = str(key)
            value = str(value)
            if not key or "=" in key or "\x00" in key:
                raise ValueError(f"invalid environment variable name: {key!r}")
            if "\x00" in value:
                raise ValueError(f"environment value for {key!r} contains NUL")
            normalized_environment[key] = value

        object.__setattr__(
            self,
            "working_directory",
            normalized_working_directory,
        )
        object.__setattr__(self, "readable_paths", readable)
        object.__setattr__(self, "writable_paths", writable)
        object.__setattr__(
            self,
            "enable_network_access",
            enable_network_access,
        )
        object.__setattr__(self, "limits", limits or SandboxLimits())
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(normalized_environment),
        )

    @classmethod
    def for_workspace(
        cls,
        root: PathInput,
        *,
        writable: bool = True,
        enable_network_access: bool = False,
        limits: SandboxLimits | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> Self:
        paths = (root,)
        return cls(
            working_directory=root,
            readable_paths=() if writable else paths,
            writable_paths=paths if writable else (),
            enable_network_access=enable_network_access,
            limits=limits or SandboxLimits(),
            environment=environment or {},
        )

    def allows_read(self, path: PathInput) -> bool:
        requested = _normalize(path)
        return _contained_by(requested, (*self.readable_paths, *self.writable_paths))

    def allows_write(self, path: PathInput) -> bool:
        requested = _normalize(path)
        return _contained_by(requested, self.writable_paths)

    def validate_working_directory(
        self,
        path: PathInput | None,
    ) -> Path:
        if path is None:
            selected = self.working_directory
        else:
            requested = Path(path).expanduser()
            base = self.working_directory or Path.cwd()
            selected = _normalize(
                requested if requested.is_absolute() else base / requested
            )
        if selected is None:
            selected = Path.cwd().resolve()
        if not selected.is_dir():
            raise NotADirectoryError(selected)
        if (self.readable_paths or self.writable_paths) and not self.allows_read(
            selected
        ):
            raise PermissionError(
                f"working directory is not allowed by sandbox policy: {selected}"
            )
        return selected


def _normalize(path: PathInput) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _normalize_optional(
    path: PathInput | None,
) -> Path | None:
    return None if path is None else _normalize(path)


def _normalize_many(
    paths: Sequence[PathInput],
) -> tuple[Path, ...]:
    normalized: list[Path] = []
    for path in paths:
        resolved = _normalize(path)
        if resolved not in normalized:
            normalized.append(resolved)
    return tuple(normalized)


def _contained_by(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False
