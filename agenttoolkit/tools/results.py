from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Provider-neutral outcome of one tool invocation."""

    ok: bool
    value: Any = None
    error: str | None = None
    respond: bool | None = None
    instruction: str | None = None

    @classmethod
    def success(
        cls,
        value: Any = None,
        *,
        respond: bool | None = None,
        instruction: str | None = None,
    ) -> Self:
        return cls(
            ok=True,
            value=value,
            respond=respond,
            instruction=instruction,
        )

    @classmethod
    def fail(cls, error: str | Exception, *, respond: bool | None = None) -> Self:
        return cls(ok=False, error=str(error), respond=respond)
