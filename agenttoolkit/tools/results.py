from dataclasses import dataclass
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    value: Any = None
    error: str | None = None

    @classmethod
    def success(cls, value: Any = None) -> Self:
        return cls(ok=True, value=value)

    @classmethod
    def fail(cls, error: str | Exception) -> Self:
        return cls(ok=False, error=str(error))
