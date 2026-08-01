from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from agenttk.builtins.todo.models import Todo, TodoStatus


@runtime_checkable
class TodoList(Protocol):
    async def add(
        self,
        content: str,
        *,
        status: TodoStatus = TodoStatus.PENDING,
    ) -> Todo: ...

    async def list(
        self,
        *,
        status: TodoStatus | None = None,
    ) -> Sequence[Todo]: ...

    async def update(
        self,
        todo_id: int,
        *,
        content: str | None = None,
        status: TodoStatus | None = None,
    ) -> Todo: ...

    async def complete(self, todo_id: int) -> Todo: ...

    async def remove(self, todo_id: int) -> Todo: ...

    async def clear(self, *, completed_only: bool = False) -> int: ...
