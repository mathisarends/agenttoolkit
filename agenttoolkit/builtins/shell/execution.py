import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

type PathInput = Path | str | os.PathLike[str]


@dataclass(frozen=True, slots=True)
class CommandLimits:
    timeout_seconds: float | None = 60.0
    max_output_bytes: int | None = 1024 * 1024

    def __post_init__(self) -> None:
        _positive("timeout_seconds", self.timeout_seconds)
        _positive("max_output_bytes", self.max_output_bytes)


@dataclass(frozen=True, slots=True, init=False)
class CommandDefaults:
    """Backend-independent defaults applied to command execution.

    `spill_directory` is opt-in: when set, output exceeding
    `limits.max_output_bytes` is written there in full instead of being
    dropped. The path is resolved on the machine running the process, which
    for a sandbox backend is the host and not the sandbox -- point it at a
    bind-mounted location if the agent is meant to read the file back.
    """

    working_directory: Path | None
    environment: Mapping[str, str]
    limits: CommandLimits
    spill_directory: Path | None

    def __init__(
        self,
        working_directory: PathInput | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        limits: CommandLimits | None = None,
        spill_directory: PathInput | None = None,
    ) -> None:
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
            None if working_directory is None else _normalize(working_directory),
        )
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(normalized_environment),
        )
        object.__setattr__(self, "limits", limits or CommandLimits())
        object.__setattr__(
            self,
            "spill_directory",
            None if spill_directory is None else _normalize(spill_directory),
        )

    def select_working_directory(self, path: PathInput | None = None) -> Path:
        if path is None:
            selected = self.working_directory or Path.cwd().resolve()
        else:
            requested = Path(path).expanduser()
            base = self.working_directory or Path.cwd()
            selected = _normalize(
                requested if requested.is_absolute() else base / requested
            )
        if not selected.is_dir():
            raise NotADirectoryError(selected)
        return selected


def _normalize(path: PathInput) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _positive(name: str, value: int | float | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be positive or None")
