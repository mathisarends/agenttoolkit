from typing import Self

from pydantic import BaseModel, ConfigDict


class ActionResult[ResultT](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    result: ResultT | None = None
    error: str | None = None

    @classmethod
    def success(cls, result: ResultT | None = None, **fields: object) -> Self:
        return cls.model_validate({"ok": True, "result": result, **fields})

    @classmethod
    def fail(cls, error: str | Exception, **fields: object) -> Self:
        return cls.model_validate({"ok": False, "error": str(error), **fields})
