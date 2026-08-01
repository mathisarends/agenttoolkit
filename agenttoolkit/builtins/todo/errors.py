class TodoError(Exception):
    pass


class TodoNotFoundError(TodoError, LookupError):
    pass


class TodoStateError(TodoError, ValueError):
    pass
