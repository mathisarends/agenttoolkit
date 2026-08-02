import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

import agenttoolkit.builtins.shell.backends.docker as docker_backend
from agenttoolkit.builtins.shell import (
    DEFAULT_TIMEOUT,
    CommandDefaults,
    CommandJobManager,
    CommandJobNotFoundError,
    CommandJobState,
    CommandJobStateError,
    CommandResult,
    CommandTimeout,
    DockerSandbox,
    SandboxPolicy,
)


class ControlledRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.timeout: CommandTimeout = DEFAULT_TIMEOUT

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: CommandTimeout = DEFAULT_TIMEOUT,
    ) -> CommandResult:
        self.timeout = timeout
        self.started.set()
        await self.release.wait()
        return CommandResult(command, 0, "finished\n", "", 0.01)


@pytest.mark.asyncio
async def test_command_jobs_start_poll_finish_and_forget() -> None:
    runner = ControlledRunner()
    async with CommandJobManager(runner) as jobs:
        started = jobs.start("build", timeout=None)
        assert started.state is CommandJobState.RUNNING
        assert not started.done
        assert started.output == ""

        await runner.started.wait()
        assert runner.timeout is None
        assert jobs.check_output(started.job_id).state is CommandJobState.RUNNING

        runner.release.set()
        await asyncio.sleep(0)
        finished = jobs.check_output(started.job_id)
        assert finished.state is CommandJobState.SUCCEEDED
        assert finished.done
        assert finished.output == "finished\n"

        jobs.forget(started.job_id)
        with pytest.raises(CommandJobNotFoundError, match="unknown command job"):
            jobs.check_output(started.job_id)


@pytest.mark.asyncio
async def test_command_jobs_cancel_and_close() -> None:
    runner = ControlledRunner()
    jobs = CommandJobManager(runner)
    first = jobs.start("train")
    await runner.started.wait()

    cancelled = await jobs.cancel(first.job_id)
    assert cancelled.state is CommandJobState.CANCELLED

    await jobs.close()
    await jobs.close()
    with pytest.raises(CommandJobStateError, match="closed"):
        jobs.start("another")


@pytest.mark.asyncio
async def test_docker_allows_concurrent_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_started = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_process(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> CommandResult:
        nonlocal exec_started
        if argv[1] == "exec":
            exec_started += 1
            if exec_started == 2:
                both_started.set()
            await release.wait()
        return CommandResult(str(kwargs["command"]), 0, "ok", "", 0.01)

    monkeypatch.setattr(docker_backend, "run_process", fake_run_process)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    async with sandbox:
        first = asyncio.create_task(sandbox.execute("first"))
        second = asyncio.create_task(sandbox.execute("second"))
        await asyncio.wait_for(both_started.wait(), timeout=1)
        release.set()
        results = await asyncio.gather(first, second)

    assert exec_started == 2
    assert all(result.ok for result in results)
