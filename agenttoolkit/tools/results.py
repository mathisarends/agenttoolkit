from typing import Self

from pydantic import BaseModel, ConfigDict


class ActionResult[ResultT = str](BaseModel):
    """Generic tool result intended for application-level specialization.

    ``ResultT`` defaults to ``str``, so a bare ``ActionResult`` is
    ``ActionResult[str]`` — and validates as one. Anything returning a
    non-string payload must parametrize explicitly, including the
    ``ActionResult[object]`` used wherever the payload type is not known
    statically.

    Bind a parametrized model to a local name when only its payload type changes::

        WeatherActionResult = ActionResult[WeatherResult]

    Subclass a parametrized model when an application or agent framework needs
    additional typed fields::

        class ProjectActionResult[ResultT](ActionResult[ResultT]):
            trace_id: str | None = None

    Pass that subclass to ``Tools(result_type=ProjectActionResult[object])`` so
    automatically wrapped values and middleware failures use the same envelope.
    """

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
