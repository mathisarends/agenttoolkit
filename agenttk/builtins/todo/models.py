from dataclasses import dataclass
from enum import StrEnum


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Todo:
    id: int
    content: str
    status: TodoStatus = TodoStatus.PENDING
