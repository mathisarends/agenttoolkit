from dataclasses import dataclass
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    value: Any = None
    error: str | None = None
    instruction: str | None = None

    @classmethod
    def success(
        cls,
        value: Any = None,
        *,
        instruction: str | None = None,
    ) -> Self:
        return cls(
            ok=True,
            value=value,
            instruction=instruction,
        )

    @classmethod
    def fail(cls, error: str | Exception) -> Self:
        return cls(ok=False, error=str(error))
