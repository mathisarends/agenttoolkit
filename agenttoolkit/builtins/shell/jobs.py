from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Self

from agenttoolkit.builtins.shell.command import CommandResult, CommandRunner
from agenttoolkit.builtins.shell.execution import DEFAULT_TIMEOUT, CommandTimeout


class CommandJobState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class CommandJobError(Exception):
    pass


class CommandJobNotFoundError(CommandJobError):
    pass


class CommandJobStateError(CommandJobError):
    pass


@dataclass(frozen=True, slots=True)
class CommandJobSnapshot:
    job_id: str
    command: str
    state: CommandJobState
    result: CommandResult | None = None
    error: str | None = None

    @property
    def done(self) -> bool:
        return self.state is not CommandJobState.RUNNING

    @property
    def output(self) -> str:
        return "" if self.result is None else self.result.output


@dataclass(frozen=True, slots=True)
class _CommandJob:
    command: str
    task: asyncio.Task[CommandResult]


class CommandJobManager:
    """Runs commands in the background and exposes polling-friendly snapshots.

    The manager owns its tasks. Use ``close()`` or ``async with`` to cancel and
    await jobs that are still running when the surrounding agent session ends.
    """

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner
        self._jobs: dict[str, _CommandJob] = {}
        self._closed = False

    def start(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: CommandTimeout = DEFAULT_TIMEOUT,
    ) -> CommandJobSnapshot:
        if self._closed:
            raise CommandJobStateError("command job manager is closed")
        if not command:
            raise ValueError("command must not be empty")

        job_id = uuid.uuid4().hex
        task = asyncio.create_task(
            self._runner.execute(
                command,
                cwd=cwd,
                env=None if env is None else dict(env),
                stdin=stdin,
                timeout=timeout,
            ),
            name=f"command-job-{job_id}",
        )
        task.add_done_callback(_consume_exception)
        self._jobs[job_id] = _CommandJob(command, task)
        return CommandJobSnapshot(job_id, command, CommandJobState.RUNNING)

    def check_output(self, job_id: str) -> CommandJobSnapshot:
        job = self._get(job_id)
        task = job.task
        if not task.done():
            return CommandJobSnapshot(job_id, job.command, CommandJobState.RUNNING)
        if task.cancelled():
            return CommandJobSnapshot(job_id, job.command, CommandJobState.CANCELLED)

        try:
            result = task.result()
        except Exception as error:
            return CommandJobSnapshot(
                job_id,
                job.command,
                CommandJobState.FAILED,
                error=f"{type(error).__name__}: {error}",
            )

        if result.timed_out:
            state = CommandJobState.TIMED_OUT
        elif result.ok:
            state = CommandJobState.SUCCEEDED
        else:
            state = CommandJobState.FAILED
        return CommandJobSnapshot(job_id, job.command, state, result=result)

    async def cancel(self, job_id: str) -> CommandJobSnapshot:
        job = self._get(job_id)
        if not job.task.done():
            job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        return self.check_output(job_id)

    def forget(self, job_id: str) -> None:
        job = self._get(job_id)
        if not job.task.done():
            raise CommandJobStateError("cannot forget a running command job")
        del self._jobs[job_id]

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = [job.task for job in self._jobs.values()]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._jobs.clear()

    async def __aenter__(self) -> Self:
        if self._closed:
            raise CommandJobStateError("command job manager is closed")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    def _get(self, job_id: str) -> _CommandJob:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise CommandJobNotFoundError(f"unknown command job: {job_id}") from error


def _consume_exception(task: asyncio.Task[CommandResult]) -> None:
    if not task.cancelled():
        task.exception()
