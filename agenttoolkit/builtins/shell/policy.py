import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

type PathInput = Path | str | os.PathLike[str]


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    memory_bytes: int | None = None
    pids: int | None = None
    cpus: float | None = None

    def __post_init__(self) -> None:
        _positive("memory_bytes", self.memory_bytes)
        _positive("pids", self.pids)
        _positive("cpus", self.cpus)


def _positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be positive or None")


@dataclass(frozen=True, slots=True, init=False)
class SandboxPolicy:
    """Isolation requirements that a sandbox backend must enforce."""

    readable_paths: tuple[Path, ...]
    writable_paths: tuple[Path, ...]
    enable_network_access: bool
    limits: SandboxLimits

    def __init__(
        self,
        *,
        readable_paths: Sequence[PathInput] = (),
        writable_paths: Sequence[PathInput] = (),
        enable_network_access: bool = False,
        limits: SandboxLimits | None = None,
    ) -> None:
        readable = _normalize_many(readable_paths)
        writable = _normalize_many(writable_paths)
        object.__setattr__(self, "readable_paths", readable)
        object.__setattr__(self, "writable_paths", writable)
        object.__setattr__(
            self,
            "enable_network_access",
            enable_network_access,
        )
        object.__setattr__(self, "limits", limits or SandboxLimits())

    @classmethod
    def for_workspace(
        cls,
        root: PathInput,
        *,
        writable: bool = True,
        enable_network_access: bool = False,
        limits: SandboxLimits | None = None,
    ) -> Self:
        paths = (root,)
        return cls(
            readable_paths=() if writable else paths,
            writable_paths=paths if writable else (),
            enable_network_access=enable_network_access,
            limits=limits or SandboxLimits(),
        )

    def allows_read(self, path: PathInput) -> bool:
        requested = _normalize(path)
        return _contained_by(requested, (*self.readable_paths, *self.writable_paths))

    def allows_write(self, path: PathInput) -> bool:
        requested = _normalize(path)
        return _contained_by(requested, self.writable_paths)

    def require_readable(self, path: PathInput) -> None:
        if (self.readable_paths or self.writable_paths) and not self.allows_read(path):
            raise PermissionError(
                f"path is not readable under sandbox policy: {_normalize(path)}"
            )


def _normalize(path: PathInput) -> Path:
    return Path(path).expanduser().resolve(strict=False)


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
