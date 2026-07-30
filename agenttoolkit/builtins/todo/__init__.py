from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, runtime_checkable


class TodoError(Exception):
    pass


class TodoNotFoundError(TodoError, LookupError):
    pass


class TodoStateError(TodoError, ValueError):
    pass


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Todo:
    id: int
    content: str
    status: TodoStatus = TodoStatus.PENDING


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


class InMemoryTodoList:
    def __init__(self) -> None:
        self._todos: dict[int, Todo] = {}
        self._next_id = 1

    async def add(
        self,
        content: str,
        *,
        status: TodoStatus = TodoStatus.PENDING,
    ) -> Todo:
        content = _validate_content(content)
        status = _validate_status(status)
        self._validate_in_progress(status)

        todo = Todo(id=self._next_id, content=content, status=status)
        self._todos[todo.id] = todo
        self._next_id += 1
        return todo

    async def list(
        self,
        *,
        status: TodoStatus | None = None,
    ) -> Sequence[Todo]:
        selected_status = None if status is None else _validate_status(status)
        return tuple(
            todo
            for todo in self._todos.values()
            if selected_status is None or todo.status is selected_status
        )

    async def update(
        self,
        todo_id: int,
        *,
        content: str | None = None,
        status: TodoStatus | None = None,
    ) -> Todo:
        todo = self._get(todo_id)
        if content is None and status is None:
            raise ValueError("content or status must be provided")

        updated_content = (
            todo.content if content is None else _validate_content(content)
        )
        updated_status = todo.status if status is None else _validate_status(status)
        if updated_status is TodoStatus.IN_PROGRESS:
            self._validate_in_progress(updated_status, except_id=todo_id)

        updated = replace(
            todo,
            content=updated_content,
            status=updated_status,
        )
        self._todos[todo_id] = updated
        return updated

    async def complete(self, todo_id: int) -> Todo:
        return await self.update(todo_id, status=TodoStatus.COMPLETED)

    async def remove(self, todo_id: int) -> Todo:
        todo = self._get(todo_id)
        del self._todos[todo_id]
        return todo

    async def clear(self, *, completed_only: bool = False) -> int:
        if not completed_only:
            count = len(self._todos)
            self._todos.clear()
            return count

        completed_ids = [
            todo.id
            for todo in self._todos.values()
            if todo.status is TodoStatus.COMPLETED
        ]
        for todo_id in completed_ids:
            del self._todos[todo_id]
        return len(completed_ids)

    def _get(self, todo_id: int) -> Todo:
        try:
            return self._todos[todo_id]
        except KeyError as error:
            raise TodoNotFoundError(f"todo does not exist: {todo_id}") from error

    def _validate_in_progress(
        self,
        status: TodoStatus,
        *,
        except_id: int | None = None,
    ) -> None:
        if status is not TodoStatus.IN_PROGRESS:
            return
        if any(
            todo.status is TodoStatus.IN_PROGRESS and todo.id != except_id
            for todo in self._todos.values()
        ):
            raise TodoStateError("only one todo may be in progress")


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    content = content.strip()
    if not content:
        raise ValueError("content must not be empty")
    return content


def _validate_status(status: TodoStatus) -> TodoStatus:
    if not isinstance(status, TodoStatus):
        raise TypeError("status must be a TodoStatus")
    return status


__all__ = [
    "InMemoryTodoList",
    "Todo",
    "TodoError",
    "TodoList",
    "TodoNotFoundError",
    "TodoStateError",
    "TodoStatus",
]
